# PostgreSQL Migration (Shared DB Config + Table Prefix)

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/postgres-migration.md)

## [S1] Problem

Persistence today is split across two unrelated mechanisms:

1. **Auth DB** (`orchestrator/db/`, `orchestrator/auth/models.py`) — already
   SQLAlchemy 2.0 async, already dual-backend by connection string
   (`sqlite+aiosqlite:///./soar.db` default, `postgresql+asyncpg://...` for
   prod), config lives in `orchestrator.config.DatabaseConfig`. But:
   - Schema is created only via `Base.metadata.create_all()`
     (`db/session.py::init_db`). There is no versioned migration path —
     `alembic` is in `requirements.txt` and mentioned in `AGENTS.md` ("Alembic
     — продакшн миграции") but no `alembic/` directory, `alembic.ini`, or a
     single migration script exists in the repo. Any future column change to
     `User`/`RefreshToken`/`ApiKey` has no upgrade path against a live
     Postgres DB with existing data.
   - Table names are fixed (`users`, `refresh_tokens`, `api_keys`). If two
     SOAR instances (e.g. stage + prod, or two customer deployments) are
     pointed at the same physical Postgres database — a common cost-saving
     setup — they collide.

2. **Job history** (`orchestrator/store/job_store.py::JobStore`) — pure
   in-memory `dict`, no relation to the DB layer at all. This is tracked as
   Known Limitations #3 and #4 in `AGENTS.md` (crash recovery is a no-op,
   history lost on restart) and is exactly what v0.7 in the roadmap
   ("Persistence: Postgres JobStore") was reserved for.

The user request ("migrate to PostgreSQL, keep SQLite backward-compatible,
switch via shared config, add a DB-name/table prefix to avoid conflicts when
a DB is shared") is v0.7: make job persistence durable via the same DB layer
auth already uses, formalize the migration path with Alembic, and add a
prefix so `database.url` can safely point at a DB shared with other
instances or apps.

## [S2] Solution Overview

- Keep **one** `database:` config section (already shared conceptually,
  now also literally shared by JobStore) as the single switch between
  SQLite and PostgreSQL — no new backend-selection field, no duplicated URL.
- Add `database.table_prefix` (default `""`) applied to every ORM table
  this project owns (`users`, `refresh_tokens`, `api_keys`, and the new
  `workflow_jobs`), so N instances can share one physical database/schema
  without name collisions.
- Introduce `AbstractJobStore` with two implementations — `InMemoryJobStore`
  (today's `JobStore`, renamed, default, zero behavior change) and
  `SQLJobStore` (new, backed by the same engine as auth) — selected by a new
  `jobs.persistence: memory | sql` field. Default stays `memory`: adopting
  Postgres is opt-in, existing deployments are untouched until they flip the
  flag.
- Add real Alembic migrations (`alembic/`) covering the three existing auth
  tables plus the new `workflow_jobs` table, generated against SQLite and
  verified against Postgres. `create_all()` stays for local/dev/test
  convenience (harmless no-op on already-migrated tables); Alembic becomes
  the documented production upgrade path.
- Add an optional `postgres` service to `deploy/stage/docker-compose.yml`
  and a stage `config.yaml` example showing the Postgres + prefix
  configuration end-to-end.

This mirrors the existing `AbstractJobQueue` → `InMemoryQueue`/`RedisQueue`
pattern already in the codebase (`orchestrator/core/queue/`), so the shape
should be familiar and reviewable by the same mental model.

## [S3] Config changes

`orchestrator/config.py`:

```python
class DatabaseConfig(BaseModel):
    url: str = "sqlite+aiosqlite:///./soar.db"
    pool_size: int = 10
    max_overflow: int = 20
    table_prefix: str = ""          # NEW


class JobsConfig(BaseModel):
    log_dir: str = "/var/log/soar/jobs"
    keep_completed: int = 1000
    persistence: str = "memory"     # NEW: memory | sql
```

`table_prefix` is validated with the same `^[a-zA-Z0-9_]*$` pattern used
elsewhere for identifiers (`orchestrator/api/validation.py::validate_name`,
adapted — underscores only, no hyphens, since it feeds directly into SQL
identifiers, not URLs/paths).

Example (`deploy/stage/config.yaml`):

```yaml
database:
  url: postgresql+asyncpg://soar:soar@postgres:5432/soar
  table_prefix: "stage_"

jobs:
  log_dir: /var/log/soar/jobs
  keep_completed: 1000
  persistence: sql
```

Dev/test default is untouched (`sqlite+aiosqlite:///./soar.db`,
`table_prefix: ""`, `persistence: memory`) — nothing changes for anyone who
doesn't edit `config.yaml`.

## [S4] Table prefix mechanism

SQLAlchemy has no built-in "prefix all tables" knob. Renaming `Table`
objects after the fact requires rewriting every `ForeignKey` colspec too, so
instead the prefix is baked in at **class-definition time**, before model
modules are imported:

`orchestrator/db/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase

_table_prefix = ""

def configure_table_prefix(prefix: str) -> None:
    global _table_prefix
    _table_prefix = prefix

def prefixed(name: str) -> str:
    return f"{_table_prefix}{name}"

def fk(table: str, column: str) -> str:
    return f"{prefixed(table)}.{column}"

class Base(DeclarativeBase):
    pass
```

Models reference these helpers instead of hardcoded strings:

```python
class User(Base):
    __tablename__ = prefixed("users")
    ...

class RefreshToken(Base):
    __tablename__ = prefixed("refresh_tokens")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey(fk("users", "id"), ondelete="CASCADE"))
    ...
```

`main.py` must call `configure_table_prefix(config.database.table_prefix)`
**before** anything imports `orchestrator.auth.models` or the new
`orchestrator.store.models` — i.e. before importing `auth.router` /
`store`. This requires moving `load_config()` to the very top of
`main.py`, ahead of the other `orchestrator.*` imports (currently config is
already loaded at module level at line 43, but after those imports — the
import order needs to flip).

**Constraint to document (AGENTS.md + this spec):** the prefix is fixed for
the lifetime of the Python process — it cannot be hot-reloaded, and
importing the model modules with one prefix then trying to reconfigure is a
no-op (classes already built). This is a one-time process-startup setting,
not a runtime-editable one — consistent with `database.url` itself, which
already requires a restart to take effect (`init_engine()` is only called
once in `lifespan`).

Alembic's `env.py` performs the same `configure_table_prefix()` call before
importing `target_metadata` so `alembic upgrade head` operates on the
correct (possibly prefixed) table names.

## [S5] SQL-backed JobStore

`orchestrator/store/base.py` (new):

```python
class AbstractJobStore(ABC):
    async def save(self, job: WorkflowJob) -> None: ...
    async def get(self, job_id: str) -> WorkflowJob | None: ...
    async def list(self, workflow_name=None, status=None, triggered_by=None, limit=50, offset=0) -> list[WorkflowJob]: ...
    async def count_by_status(self, workflow_name: str, statuses: list[JobStatus]) -> int: ...
    async def stats(self) -> dict: ...
    async def recover_on_startup(self) -> int: ...
```

`orchestrator/store/job_store.py` — today's `JobStore` renamed to
`InMemoryJobStore`, unchanged internals, now implements `AbstractJobStore`.

`orchestrator/store/models.py` (new) — one ORM table:

```python
class JobRecord(Base):
    __tablename__ = prefixed("workflow_jobs")

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_name: Mapped[str] = mapped_column(String(255), index=True)
    workflow_type: Mapped[str] = mapped_column(String(64))
    triggered_by: Mapped[str] = mapped_column(String(255))
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), index=True)
    concurrency: Mapped[str] = mapped_column(String(32))
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    timeout: Mapped[int | None] = mapped_column(Integer, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`orchestrator/store/sql_job_store.py` (new) — `SQLJobStore(AbstractJobStore)`
wrapping `async_sessionmaker`, translating `WorkflowJob` dataclass ↔
`JobRecord` row (`save` = upsert by `id`). `JSON` column type (not
`JSONB`/dialect-specific) so the same model works unmodified on SQLite and
Postgres, matching the auth models' portability approach.

`main.py` wiring:

```python
if config.jobs.persistence == "sql":
    job_store: AbstractJobStore = SQLJobStore(get_session_factory())
else:
    job_store = InMemoryJobStore(keep_completed=config.jobs.keep_completed)
```

`recover_on_startup()` on `SQLJobStore` is the real fix for Known
Limitation #3 — RUNNING jobs now survive a container restart in the DB and
can actually be marked FAILED on the next boot, instead of the current
no-op (store was empty on restart).

No caller changes needed in `JobManager`/`Worker`/API routes — they already
depend only on the public async interface (verified: no direct access to
`_jobs` outside `job_store.py` itself).

## [S6] Alembic setup

```
alembic/
├── env.py
├── script.py.mako
└── versions/
    └── 0001_initial_auth_and_jobs.py
alembic.ini
```

- `alembic.ini` — no hardcoded `sqlalchemy.url`; `env.py` reads it from
  `orchestrator.config.load_config()` (respecting `SOAR_CONFIG` env var,
  same as the app) so one config file drives both the running service and
  migrations — no drift between `config.yaml` and a separately maintained
  Alembic URL.
- `env.py` follows Alembic's documented async recipe (`asyncio.run()`
  wrapping `run_migrations_online()`) since the engine is
  `postgresql+asyncpg` / `sqlite+aiosqlite`, both async-only drivers already
  in use — no sync driver dependency added.
- `env.py` calls `configure_table_prefix(config.database.table_prefix)`
  before importing `orchestrator.auth.models` / `orchestrator.store.models`
  so `target_metadata = Base.metadata` reflects prefixed names.
- Initial migration `0001` is autogenerated against a throwaway SQLite DB
  from current `Base.metadata` (all four tables), then hand-verified against
  a local Postgres container before merging — first migration must match
  what `create_all()` produces today exactly, so upgrading an existing
  SQLite dev DB via `alembic stamp head` is safe.
- Documented commands (README/AGENTS.md):
  ```bash
  alembic upgrade head
  alembic revision --autogenerate -m "<message>"
  ```

`init_db()` (`create_all`) stays as-is for dev/test — `checkfirst=True` by
default, so it's a no-op against a DB Alembic already migrated. Production
runbook: `alembic upgrade head` before first start; app's `create_all` call
on subsequent boots is a harmless no-op.

## [S7] Deploy changes

`deploy/stage/docker-compose.yml` — add `postgres` service (mirrors the
existing `redis` service shape):

```yaml
  postgres:
    image: postgres:16-alpine
    container_name: soar-postgres
    environment:
      - POSTGRES_DB=soar
      - POSTGRES_USER=soar
      - POSTGRES_PASSWORD=${SOAR_DB_PASSWORD:-soar}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U soar"]
      interval: 10s
      timeout: 5s
      retries: 3
```

`orchestrator` service gains `depends_on: postgres: condition:
service_healthy` alongside the existing `redis` dependency; `postgres-data`
added to top-level `volumes:`.

`deploy/stage/config.yaml` gets the `database:`/`jobs:` example shown in
[S3]. SQLite stays the default in `orchestrator/config.yaml` (repo-root dev
config) — stage is where Postgres is demonstrated, matching how `queue:
backend: redis` is already stage-only vs `memory` at repo root.

## [S8] Backward compatibility

- Default `config.yaml` (no `database`/`jobs.persistence` overrides):
  identical behavior to today — SQLite file, in-memory JobStore. No
  migration is required for existing dev/test setups.
- Auth DB already runs on SQLite in tests (`aiosqlite`) — unaffected by this
  change except gaining a table prefix hook that defaults to a no-op
  (`table_prefix: ""` → `prefixed("users") == "users"`).
- Existing SQLite dev DBs with unprefixed tables continue to work — prefix
  is opt-in, not retroactively applied.
- `JobStore` symbol: keep a re-export (`InMemoryJobStore as JobStore`) in
  `orchestrator/store/job_store.py` — do **not** rename the import in
  `orchestrator/main.py` and tests without checking every reference first;
  grep shows `JobStore(` used in `main.py` and `tests/orchestrator/
  test_job_store.py`, `test_job_manager.py`, `test_worker.py`,
  `test_worker_pool.py` — these should keep working against
  `InMemoryJobStore` unchanged since it's still the default.

## [S9] Testing strategy

- `tests/orchestrator/test_sql_job_store.py` (new) — same behavioral
  contract as `tests/orchestrator/test_job_store.py` (save/get/list/
  count_by_status/stats/recover_on_startup/eviction), run against an
  in-memory SQLite engine (`sqlite+aiosqlite:///:memory:`) per test.
- `tests/orchestrator/test_table_prefix.py` (new) — spawn a subprocess (or
  use `importlib` in an isolated interpreter via `python -c`) that calls
  `configure_table_prefix("test_")` then imports the models, asserts
  `User.__tablename__ == "test_users"` and the `refresh_tokens.user_id` FK
  resolves to `test_users.id`. Subprocess isolation is required because
  prefix is fixed at first import within a process (per [S4]).
- `tests/orchestrator/test_config.py` — extend for `database.table_prefix`
  default/validation and `jobs.persistence` default/enum validation.
- Alembic: a smoke test running `alembic upgrade head` against a temp
  SQLite file and asserting the resulting schema matches
  `Base.metadata` (table/column names) — catches drift between the
  autogenerated migration and current models.
- No CI Postgres container is assumed to exist yet — Postgres-specific
  behavior (`asyncpg` connection, pool sizing) is exercised manually via
  `deploy/stage` per [S7], not in the unit test suite, consistent with how
  `RedisQueue` unit-tests mock Redis and rely on `deploy/stage` for the real
  thing.

## [S10] Open decision for review

`jobs.persistence` defaults to `memory` (opt-in SQL) rather than making
`SQLJobStore` the new unconditional default. Rationale: matches this
project's established caution around swapping load-bearing infra by default
(see v0.5.3 IRP rollback rationale in `AGENTS.md`) and avoids adding a DB
round-trip to every job status transition for deployments that don't need
persistence yet. If persistent job history should become the default
behavior instead of opt-in, flip the `JobsConfig.persistence` default to
`"sql"` in the plan — no other part of this design changes.

## [S11] Success criteria

- [ ] `database.url` switch between SQLite/Postgres works for **both** auth
      and job history from one shared `database:` config section
- [ ] `database.table_prefix` applied consistently to all four tables,
      including FK targets, verified on both SQLite and Postgres
- [ ] `alembic upgrade head` produces a schema byte-for-byte equivalent to
      current `create_all()` output (initial migration), and is the
      documented production path
- [ ] `jobs.persistence: sql` makes `JobStore.recover_on_startup()`
      actually recover jobs across a container restart (fixes Known
      Limitation #3/#4)
- [ ] Default config (no edits) behaves identically to pre-change behavior
- [ ] `deploy/stage` demonstrates the full Postgres + prefix setup and
      starts cleanly with `docker compose up --build`
- [ ] All existing tests pass unmodified; new tests cover `SQLJobStore` and
      prefix isolation
