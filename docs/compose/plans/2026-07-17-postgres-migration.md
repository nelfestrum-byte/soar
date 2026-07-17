# Plan: PostgreSQL Migration (Shared DB Config + Table Prefix)

Spec: [`docs/compose/specs/2026-07-17-postgres-migration-design.md`](../specs/2026-07-17-postgres-migration-design.md)

Decision from spec review: `jobs.persistence` defaults to `memory` and stays
available as a first-class option — `sql` is opt-in, not a replacement.

## Phase 1 — Config fields

- [ ] Add failing assertions to `tests/orchestrator/test_config.py`:
  - `OrchestratorConfig().database.table_prefix == ""`
  - `OrchestratorConfig().jobs.persistence == "memory"`
  - `load_config()` from a YAML with `database: {table_prefix: "stage_"}` and
    `jobs: {persistence: sql}` round-trips both fields
- [ ] `orchestrator/config.py`: add `table_prefix: str = ""` to
  `DatabaseConfig`, `persistence: str = "memory"` to `JobsConfig`
- [ ] Run `python -m pytest tests/orchestrator/test_config.py -v`

## Phase 2 — Table prefix mechanism

- [ ] Write `tests/orchestrator/test_table_prefix.py` (new file). Since the
  prefix is baked in at model-import time (per spec [S4]), the test must run
  in an isolated subprocess so it doesn't pollute the rest of the suite's
  already-imported `orchestrator.auth.models` / `orchestrator.store.models`.
  Use `subprocess.run([sys.executable, "-c", "..."])` with an inline script
  that:
  1. imports `orchestrator.db.base`, calls `configure_table_prefix("test_")`
  2. imports `orchestrator.auth.models` and `orchestrator.store.models`
  3. asserts `User.__tablename__ == "test_users"`,
     `RefreshToken.__tablename__ == "test_refresh_tokens"`,
     `ApiKey.__tablename__ == "test_api_keys"`,
     `JobRecord.__tablename__ == "test_workflow_jobs"`
  4. asserts the FK colspec on `RefreshToken.user_id` resolves to
     `"test_users.id"` (via
     `RefreshToken.__table__.c.user_id.foreign_keys` → `.target_fullname`)
  5. exits non-zero on `AssertionError` so the outer pytest test can assert
     `returncode == 0`
  This test fails now — `configure_table_prefix`/`prefixed`/`fk` don't exist.
- [ ] `orchestrator/db/base.py`: add module-level `_table_prefix = ""`,
  `configure_table_prefix(prefix: str) -> None`, `prefixed(name: str) -> str`,
  `fk(table: str, column: str) -> str` (see spec [S4] for exact signatures)
- [ ] `orchestrator/auth/models.py`: replace hardcoded `__tablename__`
  strings with `prefixed("users")` / `prefixed("refresh_tokens")` /
  `prefixed("api_keys")`; replace `ForeignKey("users.id", ...)` with
  `ForeignKey(fk("users", "id"), ...)`
- [ ] Run `python -m pytest tests/orchestrator/test_table_prefix.py -v`
- [ ] Run full auth test suite to confirm empty-prefix default is a no-op:
  `python -m pytest tests/orchestrator/api/test_auth_api.py tests/orchestrator/api/test_webhook_auth.py -v`
- [ ] Add `table_prefix` format validation (`^[a-zA-Z0-9_]*$`, no hyphens —
  it feeds SQL identifiers) to `DatabaseConfig` as a Pydantic field
  validator; add a `test_config.py` case for a rejected value
  (e.g. `"bad-prefix"`)

## Phase 3 — `AbstractJobStore` + rename existing store

- [ ] Write `tests/orchestrator/store/test_abstract_job_store.py` asserting
  `InMemoryJobStore` and (later) `SQLJobStore` both satisfy
  `isinstance(store, AbstractJobStore)` — fails immediately (no
  `AbstractJobStore`, no `InMemoryJobStore` yet)
- [ ] `orchestrator/store/base.py` (new): `AbstractJobStore(ABC)` per spec
  [S5] — `save`, `get`, `list`, `count_by_status`, `stats`,
  `recover_on_startup`, matching the exact signatures currently in
  `orchestrator/store/job_store.py`
- [ ] `orchestrator/store/job_store.py`: rename class `JobStore` →
  `InMemoryJobStore(AbstractJobStore)`; add `JobStore = InMemoryJobStore`
  alias at module bottom so none of the ~14 existing call sites
  (`main.py`, `job_manager.py`, `worker.py`, `worker_pool.py`, and all
  `tests/orchestrator/**` files importing `JobStore`) need to change
- [ ] Run full existing suite to confirm the rename+alias is invisible:
  `python -m pytest tests/orchestrator/ -v`

## Phase 4 — `JobRecord` ORM model + `SQLJobStore`

- [ ] Write `tests/orchestrator/store/test_sql_job_store.py` mirroring
  `tests/orchestrator/test_job_store.py` test-for-test (same 9 cases:
  save/get, get-not-found, list, list-filter-workflow-name,
  list-filter-status, count_by_status, stats, recover_on_startup ×2), but
  fixture builds `SQLJobStore` against an in-memory SQLite engine —
  follow the `db_engine`/`db_factory` fixture pattern already used in
  `tests/orchestrator/api/test_auth_api.py` (`create_async_engine`,
  `Base.metadata.create_all`/`drop_all`). Fails now — `SQLJobStore`,
  `JobRecord` don't exist.
- [ ] `orchestrator/store/models.py` (new): `JobRecord(Base)` per spec [S5]
  field list, `__tablename__ = prefixed("workflow_jobs")`
- [ ] `orchestrator/store/sql_job_store.py` (new): `SQLJobStore` implementing
  `AbstractJobStore`, `__init__(self, session_factory)`, `save()` = upsert
  by `id` (merge), dataclass↔row mapping for `WorkflowJob ↔ JobRecord`
  (note: `WorkflowJob.status`/`.concurrency` are `StrEnum` — store `.value`,
  reconstruct via `JobStatus(row.status)` / `ConcurrencyPolicy(row.concurrency)`)
- [ ] Run `python -m pytest tests/orchestrator/store/test_sql_job_store.py -v`
- [ ] Confirm identical behavior against Postgres semantics that SQLite
  doesn't enforce (e.g. `JSON` column read-back type) is out of scope for
  unit tests — deferred to manual `deploy/stage` verification (Phase 7)

## Phase 5 — Wire persistence switch into `main.py`

- [ ] Move `_startup_config_path`/`_startup_config` load (currently at
  `main.py:42-43`, after `orchestrator.auth.router` is already imported at
  line 25) to the **top** of `main.py`, before any other `orchestrator.*`
  import, and call `configure_table_prefix(_startup_config.database.table_prefix)`
  immediately after — this must happen before `orchestrator.auth.router` /
  `orchestrator.store.models` are imported anywhere in the module. Remove
  the now-duplicate load at the old location; reuse `_startup_config`
  wherever CORS setup currently re-reads it.
- [ ] In `lifespan()`, after `init_engine`/`init_db`/`app.state.db_session_factory`
  (`main.py:144-147`), replace the unconditional
  `job_store = JobStore(keep_completed=config.jobs.keep_completed)` with:
  ```python
  if config.jobs.persistence == "sql":
      job_store: AbstractJobStore = SQLJobStore(get_session_factory())
  else:
      job_store = InMemoryJobStore(keep_completed=config.jobs.keep_completed)
  ```
- [ ] Add a `test_main.py` (or extend an existing lifespan/startup test if
  one exists — check `tests/orchestrator/` first) asserting
  `app.state` ends up with an `InMemoryJobStore` by default and a
  `SQLJobStore` when `jobs.persistence: sql` is set in the loaded config
- [ ] Run `python -m pytest tests/orchestrator/ -v` (full suite — this step
  touches shared startup wiring)

## Phase 6 — Alembic

- [ ] Add `alembic/` (`env.py`, `script.py.mako`, `versions/`) and
  `alembic.ini` at repo root per spec [S6] — async env recipe
  (`asyncio.run(run_migrations_online())`), reads URL via
  `orchestrator.config.load_config()` respecting `SOAR_CONFIG`, calls
  `configure_table_prefix()` before importing `orchestrator.auth.models` /
  `orchestrator.store.models`, `target_metadata = Base.metadata`
- [ ] Generate initial migration against a scratch SQLite DB:
  `alembic revision --autogenerate -m "initial auth and jobs tables"`,
  hand-review the generated `versions/0001_*.py` for exact column types
  matching `User`/`RefreshToken`/`ApiKey`/`JobRecord`
- [ ] Verify manually against a local Postgres (`docker run --rm -p 5433:5432
  -e POSTGRES_PASSWORD=test postgres:16-alpine`, then
  `SOAR_CONFIG=... alembic upgrade head` against it) — confirm all 4 tables
  and FKs land correctly, then `alembic downgrade base` to confirm the
  downgrade path doesn't error
- [ ] Write `tests/orchestrator/test_alembic_schema.py`: run
  `alembic upgrade head` against a temp SQLite file (via `alembic.config`
  API, not shelling out), reflect the resulting schema, assert table/column
  names match `Base.metadata` (catches drift between migration and models)
- [ ] Document commands in `AGENTS.md` Commands section (after Phase 8):
  `alembic upgrade head`, `alembic revision --autogenerate -m "<msg>"`

## Phase 7 — Deploy

- [ ] `deploy/stage/docker-compose.yml`: add `postgres` service (image
  `postgres:16-alpine`, `POSTGRES_DB=soar`, `POSTGRES_USER=soar`,
  `POSTGRES_PASSWORD=${SOAR_DB_PASSWORD:-soar}`, `postgres-data` volume,
  `pg_isready` healthcheck) per spec [S7]; add
  `depends_on: postgres: condition: service_healthy` to `orchestrator`
  alongside the existing `redis` dependency
- [ ] `deploy/stage/config.yaml`: add
  ```yaml
  database:
    url: postgresql+asyncpg://soar:soar@postgres:5432/soar
    table_prefix: "stage_"

  jobs:
    log_dir: /var/log/soar/jobs
    keep_completed: 100
    persistence: sql
  ```
- [ ] Manual verification: `cd deploy/stage && docker compose up --build`,
  confirm orchestrator starts, `GET /status` healthy, run a workflow job via
  API, confirm the job row lands in Postgres with `stage_` prefix
  (`docker compose exec postgres psql -U soar -d soar -c '\dt'`), restart
  the `orchestrator` container, confirm the job is still visible via
  `GET /jobs/{id}` (validates the crash-recovery fix, Known Limitation #3)

## Phase 8 — Docs

- [ ] Update `AGENTS.md`:
  - `Architecture` tree: add `orchestrator/store/base.py`,
    `orchestrator/store/models.py`, `orchestrator/store/sql_job_store.py`,
    `alembic/`
  - New subsection under "Key patterns" documenting the `database:`/`jobs:`
    switch (mirror the existing "Queue backend" subsection style) —
    memory/sql persistence, table_prefix, Alembic commands
  - Remove/update Known Limitations #3 and #4 (no longer apply when
    `jobs.persistence: sql`; note they still apply under the `memory`
    default)
  - `File map` table: add rows for `store/base.py`, `store/sql_job_store.py`,
    `alembic/`
  - `Version history`: add v0.7 entry summarizing this change
- [ ] Write `docs/compose/reports/postgres-migration.md` per repo report
  convention (frontmatter + what changed + verification performed)

## Test commands (run after each phase, full suite before considering done)

```bash
python -m pytest tests/ -v
ruff check .
mypy orchestrator/ soar/ --ignore-missing-imports
```
