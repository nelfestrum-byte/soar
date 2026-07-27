# Plan: SQL-Backed Job Queue + Job History Retention

Spec: `docs/compose/specs/2026-07-27-sql-job-queue-design.md`

## Mapping extraction

- [x] Create `orchestrator/store/mapping.py` with `_ensure_utc`, `_ensure_utc_required`,
      `job_to_record`, `record_to_job` (public names — used across two modules now)
- [x] Update `orchestrator/store/sql_job_store.py` to import from `mapping.py`, drop the
      local private copies, keep call sites working (`_job_to_record(job)` → `job_to_record(job)`)
- [x] Existing `test_sql_job_store.py` tests still pass unchanged (regression)

## Tests first (fail before implementation)

- [x] `tests/orchestrator/core/queue/__init__.py` (new package dir) +
      `tests/orchestrator/core/queue/test_sql_queue.py`:
      - push/pop round trip against `sqlite+aiosqlite:///:memory:`
      - `push()` does not create a duplicate row when the row already exists (saved via
        `job_store.save()` first)
      - pop returns `None` when no PENDING rows exist (single fast poll, no long wait)
      - concurrent claim: two parallel `pop()` calls against one PENDING row — exactly one
        gets the job, claimed row's status becomes RUNNING
      - `size()` counts only PENDING rows; `clear()` no-op semantics (documented, since
        SQLQueue does not own the rows) — decide exact semantics while writing the test
      - `health()` reports basic connectivity info
- [x] `tests/orchestrator/test_main_job_store_factory.py`: add
      `test_create_queue_sql_requires_sql_persistence_raises` and
      `test_create_queue_sql_with_sql_persistence_ok`
- [x] `tests/orchestrator/store/test_sql_job_store.py`: add `purge_old()` tests — deletes
      only COMPLETED/FAILED/TIMEOUT/CANCELLED older than threshold, leaves RUNNING/PENDING
      alone regardless of age, returns deleted count
- [x] Confirm the above tests fail (missing symbols) before implementing

## Implementation

- [x] `orchestrator/store/base.py`: add abstract `purge_old(self, retention_days: int) -> int`
- [x] `orchestrator/store/job_store.py` (`InMemoryJobStore`): `purge_old()` → `return 0` (no-op,
      `keep_completed` already bounds size)
- [x] `orchestrator/store/sql_job_store.py`: implement `purge_old()` per [S6] DELETE query
- [x] `orchestrator/core/queue/sql_queue.py` (new): `SQLQueue(AbstractJobQueue)`
      - `__init__(self, session_factory, poll_interval: float = 0.5)`
      - `push()`: no-op (row already written by `JobManager.enqueue()` via `job_store.save()`)
      - `pop(timeout)`: loop of claim-attempt + `asyncio.sleep(poll_interval)` until timeout
        elapses; claim = single UPDATE...WHERE id=(SELECT...LIMIT 1) using dialect branch
        (`session.bind.dialect.name == "postgresql"` → add `FOR UPDATE SKIP LOCKED` via raw
        SQL / Core `.with_for_update(skip_locked=True)`; sqlite → same UPDATE without it)
      - `size()`: count PENDING rows
      - `clear()`: delete/reset PENDING rows back — documented behavior (SQLQueue doesn't own
        a separate list, unlike Redis/InMemory)
      - `health()`: report `{"connected": True/False, "size": n}`
- [x] `orchestrator/config.py`: `QueueConfig.sql_poll_interval: float = 0.5`;
      `JobsConfig.retention_days: int = 0` — additive only, no reformatting of unrelated lines
      (shared file with another agent's HttpClientConfig work)
- [x] `orchestrator/main.py::create_queue()`: add `"sql"` branch with fail-fast `ValueError`
      when `jobs.persistence != "sql"`
- [x] `orchestrator/core/scheduler.py`: `OrchestratorScheduler.start(workflows, retention_days=0)`
      registers `IntervalTrigger(hours=24)` job `"retention_cleanup"` calling
      `self._job_manager.job_store.purge_old(retention_days)` + logging deleted count, only if
      `retention_days > 0`
- [x] `orchestrator/main.py::lifespan()`: pass `config.jobs.retention_days` to `scheduler.start()`
- [x] `alembic/versions/<rev>_add_workflow_jobs_pending_index.py` (new): partial index per [S5]
- [x] `orchestrator/store/models.py`: doc-comment noting the partial index (migration-only,
      no ORM-level `Index(...)` needed — `test_alembic_schema.py` only compares tables/columns,
      not indexes)
- [x] `deploy/prod/config.yaml.template`: `queue.backend: sql`, `jobs.retention_days: 90`
      (with comment)
- [x] `deploy/stage/config.yaml`: same switch, for consistency

## Verification

- [x] Run new tests, confirm pass
- [x] Run full `python -m pytest`, confirm no regressions (601 existing + new)
- [x] Confirm `test_alembic_schema.py` still passes (migration applies cleanly on sqlite)

## Docs

- [x] `docs/compose/reports/sql-job-queue.md` after implementation
