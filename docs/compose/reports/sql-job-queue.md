# Report: SQL-Backed Job Queue + Job History Retention

Spec: `docs/compose/specs/2026-07-27-sql-job-queue-design.md`
Plan: `docs/compose/plans/2026-07-27-sql-job-queue.md`

## Summary

Implemented `SQLQueue(AbstractJobQueue)` as a poll-based queue over the
existing `workflow_jobs` table, closing the at-most-once job-loss window in
`RedisQueue.pop()` (BRPOP can drop a job between Redis removing it and the
network delivering the response). Added `jobs.retention_days` config +
`purge_old()` on the job store ABC, wired into the existing
`OrchestratorScheduler` as a 24h interval job. Extracted `_job_to_record`/
`_record_to_job` out of `sql_job_store.py` into a new shared
`orchestrator/store/mapping.py`, used by both `SQLJobStore` and `SQLQueue`.
Added a partial index migration and switched both deploy templates from
`queue.backend: redis` to `sql`.

## Files changed

New:
- `orchestrator/core/queue/sql_queue.py` — `SQLQueue`: `push()` no-op,
  `pop()` = poll loop of atomic claim attempts (`UPDATE ... WHERE id =
  (SELECT ... ORDER BY triggered_at LIMIT 1) AND status = 'PENDING'`, with
  `FOR UPDATE SKIP LOCKED` added via `.with_for_update(skip_locked=True)`
  only on the `postgresql` dialect branch; SQLite relies on file-level
  write-transaction serialization for the same guarantee), `size()` counts
  PENDING rows, `clear()` marks PENDING rows CANCELLED (SQLQueue has no
  separate list to clear — the rows *are* the queue), `health()` reports
  connectivity + size.
- `orchestrator/store/mapping.py` — `job_to_record`/`record_to_job`/
  `ensure_utc`/`ensure_utc_required`, moved out of `sql_job_store.py` (was
  module-private there), now shared by `SQLJobStore` and `SQLQueue`.
- `alembic/versions/42fbd47b0d46_add_workflow_jobs_pending_index.py` —
  partial index `ix_workflow_jobs_pending_triggered_at` on
  `(status, triggered_at) WHERE status = 'PENDING'`, `postgresql_where`/
  `sqlite_where`, literal table name `workflow_jobs` (matches existing
  migration precedent that doesn't account for `table_prefix`, known-limitation
  #9 — not fixed here, out of scope).
- `tests/orchestrator/core/queue/test_sql_queue.py` — push/pop round trip,
  no-duplicate-row on push, empty-queue None, FIFO ordering by
  `triggered_at`, concurrent-pop-claims-exactly-once, size-counts-pending-
  only, health.
- `docs/compose/plans/2026-07-27-sql-job-queue.md`

Modified:
- `orchestrator/store/sql_job_store.py` — imports mapping from
  `mapping.py` instead of local private functions; added `purge_old()`
  (`DELETE ... WHERE status IN (COMPLETED, FAILED, TIMEOUT, CANCELLED) AND
  finished_at < now() - retention_days`, returns deleted row count, logs
  when > 0).
- `orchestrator/store/base.py` — new abstract `purge_old(retention_days:
  int) -> int` on `AbstractJobStore`.
- `orchestrator/store/job_store.py` — `InMemoryJobStore.purge_old()` is a
  no-op returning 0 (`keep_completed` already bounds size).
- `orchestrator/store/models.py` — doc-comment on `JobRecord` pointing at
  the partial-index migration (no ORM-level `Index(...)` added —
  `test_alembic_schema.py` only diffs tables/columns, not indexes).
- `orchestrator/config.py` — additive only: `QueueConfig.sql_poll_interval:
  float = 0.5`, `JobsConfig.retention_days: int = 0`.
- `orchestrator/main.py` — `create_queue()` gets a `"sql"` branch that
  fail-fasts with `ValueError` when `jobs.persistence != "sql"`;
  `lifespan()` now passes `config.jobs.retention_days` into
  `scheduler.start()`.
- `orchestrator/core/scheduler.py` — `OrchestratorScheduler.start()` takes
  a new `retention_days: int = 0` param; when > 0, registers an
  `IntervalTrigger(hours=24)` job `"retention_cleanup"` that calls
  `self._job_manager.job_store.purge_old(retention_days)` and logs the
  deleted count (or the failure, without crashing the scheduler).
- `deploy/prod/config.yaml.template` — `queue.backend: sql` (was `redis`),
  `+ sql_poll_interval: 0.5`, `+ jobs.retention_days: 90`.
- `deploy/stage/config.yaml` — same switch, `jobs.retention_days: 30`
  (smaller footprint than prod, still explicit non-zero per spec principle
  of no silent defaults).
- `tests/orchestrator/test_main_job_store_factory.py` — added
  `test_create_queue_defaults_to_in_memory`,
  `test_create_queue_sql_requires_sql_persistence_raises`,
  `test_create_queue_sql_with_sql_persistence_ok`.
- `tests/orchestrator/store/test_sql_job_store.py` — added
  `test_sql_job_store_purge_old_deletes_only_terminal_statuses_past_threshold`
  (verifies RUNNING/PENDING rows are never purged regardless of age) and
  `test_sql_job_store_purge_old_returns_zero_when_nothing_old`.
- `tests/orchestrator/test_job_store.py` — added
  `test_purge_old_is_a_noop_for_in_memory_store`.

## Deviations from spec / notes

- `clear()` semantics for `SQLQueue` aren't specified in [S4]/[S7]; chosen
  behavior (mark PENDING rows CANCELLED) mirrors "empty the queue" intent
  without touching RUNNING/terminal rows, and is exercised implicitly (not
  by a dedicated test — no existing queue test asserts `clear()`'s exact
  side effect beyond "queue becomes empty", and `AbstractJobQueue.clear()`
  has no return value to assert against).
- `deploy/stage/config.yaml` retention set to `30` days (not specified in
  spec, which only gives `90` for prod as an example); reasoned choice for
  a lower-traffic stage environment, still an explicit non-zero value per
  the "no silent defaults" principle from [S6].
- Migration revision id `42fbd47b0d46` generated locally (not via `alembic
  revision`, since this environment doesn't run migrations against a live
  target during authoring) — `down_revision` correctly chains to the
  existing head `3067dea7c75b`.

## Test results

New/updated tests: 7 (`test_sql_queue.py`) + 3 (`test_main_job_store_factory.py`)
+ 2 (`test_sql_job_store.py` purge_old) + 1 (`test_job_store.py` purge_old) = 13 new.

Full suite: `python -m pytest -q`

```
4 failed, 609 passed, 1 skipped, 16 warnings in 105.19s
```

The 4 failures are pre-existing and unrelated to this change (confirmed via
`git stash` against unmodified HEAD, same 4 failures reproduce):
- `tests/orchestrator/test_redis_integration.py` (3 tests) — require a live
  Redis server on `localhost:6379`; not available in this sandbox. The
  fixture's `pytest.skip` guard doesn't trigger because `RedisQueue.clear()`
  swallows connection errors internally, so the failure surfaces later in
  the test body instead of the fixture — a pre-existing test issue, not
  touched by this change.
- `tests/soar/tools/test_openapi.py::test_generate_config` — in
  `soar/tools/`, explicitly out of scope for this task (owned by another
  agent's parallel work).

All tests touching files this spec modifies — `test_sql_job_store.py`,
`test_abstract_job_store.py`, `test_job_store.py`, `test_redis_queue.py`,
`test_alembic_schema.py`, `test_main_job_store_factory.py`, and the new
`test_sql_queue.py` — pass (40/40 in that targeted run, plus the 609 in the
full run).

## Success criteria (spec [S10])

- [x] `SQLQueue` implements `AbstractJobQueue`; claim is atomic on Postgres
      (`with_for_update(skip_locked=True)`) and on SQLite (write-transaction
      serialization); verified by a concurrent-`pop()` test.
- [x] `push()` doesn't create an extra row — reuses the row
      `JobManager.enqueue()` already saved.
- [x] `queue.backend: sql` without `jobs.persistence: sql` raises `ValueError`
      at `create_queue()` time (fail-fast, not a silent broken mode).
- [x] Partial index `(status, triggered_at) WHERE status='PENDING'` added via
      migration; verified against both `postgresql_where`/`sqlite_where`
      compiled output and via `test_alembic_schema.py` (upgrade head runs
      clean).
- [x] `jobs.retention_days` defaults to `0` (disabled) at the schema level;
      explicit non-zero values set in both deploy configs.
- [x] `purge_old()` implemented in `SQLJobStore`, no-op in `InMemoryJobStore`,
      called on a schedule via the existing `OrchestratorScheduler` — no new
      deploy component.
- [x] `deploy/prod/config.yaml.template` and `deploy/stage/config.yaml`
      switched to `queue.backend: sql`.
- [x] All existing queue/job-store tests pass unchanged.
