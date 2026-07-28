# Report: Purge Job Log Files Alongside DB Retention (S5)

Spec: `docs/compose/specs/2026-07-28-job-log-purge-design.md`
Plan: `docs/compose/plans/2026-07-28-job-log-purge.md`

## Summary

`SQLJobStore.purge_old()` (`orchestrator/store/sql_job_store.py`) deleted
`workflow_jobs` rows past `retention_days` but never touched the
corresponding `.log` files on disk. On any deployment with a non-zero
retention (`deploy/prod`: 90 days), this guaranteed unbounded disk growth
from orphaned log files — once a row was deleted, `log_path` was lost from
both the DB and process memory, so no later run of `purge_old` could ever
find and remove the file.

Implemented per spec [S2]:

1. Before the `DELETE`, run a `SELECT JobRecord.log_path` under the same
   `WHERE` clause (terminal status, `finished_at < threshold`,
   `log_path IS NOT NULL`) to collect the paths that are about to lose
   their only reference.
2. Run the existing `DELETE` + `commit` unchanged.
3. After a successful commit, iterate the collected paths and `os.remove`
   each one: `FileNotFoundError` is swallowed (already removed manually or
   by an incomplete prior run — not an error); any other `OSError` is
   logged via `logger.warning` and does not propagate.

Two separate `SELECT`+`DELETE` queries in the same session, not a single
`DELETE ... RETURNING log_path` — per spec, `RETURNING` doesn't map
identically across the project's two supported backends (SQLite/Postgres)
through the current SQLAlchemy Core style, and the extra `SELECT` costs
nothing meaningful at the call frequency (once per 24h).

## Files changed

- `orchestrator/store/sql_job_store.py` — `import os`; `purge_old()`
  rewritten per spec [S2].
- `tests/orchestrator/store/test_sql_job_store.py` — three new tests:
  `test_sql_job_store_purge_old_removes_log_files`,
  `test_sql_job_store_purge_old_survives_missing_log_file`,
  `test_sql_job_store_purge_old_ignores_null_log_path`.

## Testing

New tests were added first and confirmed failing against the pre-change
code (the two log-file tests failed — rows were deleted but files were
left on disk; the null-log-path test already passed since the pre-change
code never touched files at all).

`tests/orchestrator/store/`:

```
18 passed, 1 warning in 0.91s
```

Full suite:

```
1 failed, 689 passed, 1 skipped, 13 warnings in 85.98s (0:01:25)
```

The one failure is the pre-existing, unrelated
`tests/soar/tools/test_openapi.py::test_generate_config` (uses the
connector class name instead of the requested connector name as the
instance key in generated config; tracked separately). No new failures
introduced.

## Success criteria (spec [S5])

- [x] `purge_old()` removes log files together with DB rows, within the
      same call
- [x] Order of operations: collect paths → delete rows → commit → remove
      files (files untouched if the transaction doesn't commit)
- [x] A single file-removal failure doesn't interrupt cleanup of the rest
      and doesn't raise — only `logger.warning`
- [x] `InMemoryJobStore`/`AbstractJobStore.purge_old()` interface
      unchanged, no regression
- [x] On prod (`retention_days: 90`), disk no longer grows unboundedly
      from job logs older than the retention window

Not in scope (per spec, explicitly deferred to an operator/Day-2-ops
decision): log files orphaned by runs of `purge_old` that already happened
*before* this fix — a one-time manual filesystem cleanup, not addressed
by this change.
