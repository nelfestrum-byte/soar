# Report: Pending-Index on Fresh Installs + Migration `table_prefix` Fix

Spec: `docs/compose/specs/2026-07-28-workflow-jobs-index-table-prefix-design.md`
Plan: `docs/compose/plans/2026-07-28-workflow-jobs-index-table-prefix.md`

## Summary

Fixed BAGFIX_PLAN S6: the partial index
`ix_workflow_jobs_pending_triggered_at` on `workflow_jobs(status,
triggered_at) WHERE status='PENDING'` was declared only in the Alembic
migration `42fbd47b0d46`, not in the `JobRecord` model. The documented
fresh-install sequence (`soarctl up && soarctl migrate --fresh`) runs
`create_all()` (from `Base.metadata`) followed by `alembic stamp head`,
which stamps the revision as applied but never executes its DDL — so
every fresh production install silently ended up without the index that
keeps `SQLQueue.pop()`'s claim query cheap. Separately, two migrations
(`42fbd47b0d46` and `3067dea7c75b`) hardcoded literal table/index names
instead of routing them through `prefixed()`, breaking
`database.table_prefix` support (used today by `deploy/stage`,
`table_prefix: "stage_"`) whenever `alembic upgrade head` runs instead of
`--fresh`.

## Files changed

New:
- `orchestrator/store/models.py` — `JobRecord.__table_args__` now
  declares `Index(f"ix_{prefixed('workflow_jobs')}_pending_triggered_at",
  "status", "triggered_at", postgresql_where=text("status = 'PENDING'"),
  sqlite_where=text("status = 'PENDING'"))`. Same name as the migration's
  index (both resolve through `prefixed()`) — `create_all()` and
  `alembic upgrade head` are two independent triggers for the same
  result, not duplication to remove.
- `tests/orchestrator/store/test_job_record_index.py` (new file — named
  to avoid a pytest basename collision with the existing
  `tests/orchestrator/test_models.py`; neither `tests/orchestrator/` nor
  `tests/orchestrator/store/` has an `__init__.py`) —
  `test_create_all_creates_pending_index`: `Base.metadata.create_all()`
  on a plain SQLite engine, asserts the index name is present in
  `sqlite_master`.
- `tests/orchestrator/test_alembic_schema.py` —
  `test_alembic_upgrade_head_respects_table_prefix`: writes a
  `config.yaml` with `database.table_prefix: "test_"`, runs `alembic
  upgrade head` as a subprocess (same pattern as the existing
  `test_alembic_upgrade_head_matches_orm_metadata`), asserts every
  reflected table is prefixed (`test_workflow_jobs`, `test_audit_log`,
  `test_users`, `test_api_keys`, `test_refresh_tokens`) and that no
  index carries the old unprefixed bug names (`ix_workflow_jobs_pending_
  triggered_at`, `ix_audit_log_*`).
- `docs/compose/plans/2026-07-28-workflow-jobs-index-table-prefix.md`
- `docs/compose/specs/2026-07-28-workflow-jobs-index-table-prefix-design.md`
  (added to this worktree — was written directly in the shared checkout
  and had not yet been committed on any branch)

Modified:
- `alembic/versions/42fbd47b0d46_add_workflow_jobs_pending_index.py` —
  index/table names now go through `prefixed()`
  (`f"ix_{prefixed('workflow_jobs')}_pending_triggered_at"`,
  `prefixed("workflow_jobs")`), matching the model's index name exactly.
  Corrected the module docstring, which claimed `ea0bb43fc071` and
  `3067dea7c75b` "already don't account for `database.table_prefix`" —
  `ea0bb43fc071` was already correct; only `3067dea7c75b` had the bug,
  fixed in this same change.
- `alembic/versions/3067dea7c75b_add_audit_log_table.py` —
  `create_table`/`create_index`/`drop_index`/`drop_table` now use
  `prefixed('audit_log')` and `f"ix_{prefixed('audit_log')}_*"` instead
  of literal `'audit_log'`/`op.f('ix_audit_log_*')`.
  `ea0bb43fc071_initial_auth_and_jobs_tables.py` was already correct and
  is untouched. No `revision`/`down_revision` identifiers changed on
  either migration — only migration bodies, per the spec's rationale
  ([S2.2]): empty `table_prefix` installs see no behavior change
  (`prefixed(x) == x`), only future `upgrade head` runs against a
  non-empty `table_prefix` are affected.
- `docs/concepts/UPGRADE-v2.md` — P14 entry now notes the index is
  declared in both the model and the migration, guaranteed on any
  install path, not only the upgrade path.
- `docs/compose/specs/2026-07-27-sql-job-queue-design.md` — [S5]
  annotated with an update block pointing at this track, explaining the
  model now also declares the same index and why the migration remains
  necessary (upgrades of pre-existing installs, where `create_all()`
  doesn't touch an already-existing table).

## Test results

New tests confirmed failing before implementation (index test: no
`Index` on `JobRecord`; prefix test: literal names in both migrations),
then passing after:

```
tests/orchestrator/store/test_job_record_index.py::test_create_all_creates_pending_index PASSED
tests/orchestrator/test_alembic_schema.py::test_alembic_upgrade_head_respects_table_prefix PASSED
```

Targeted run (`tests/orchestrator/store/` + `test_alembic_schema.py`):
18 passed.

Full suite:

```
python -m pytest tests/ -q
1 failed, 688 passed, 1 skipped, 13 warnings in 92.23s
```

The one failure is the known pre-existing
`tests/soar/tools/test_openapi.py::test_generate_config` (unrelated,
fixed by a separate spec) — confirmed as the only failure, zero
regressions introduced.

## Success criteria (spec [S4])

- [x] Partial index exists after `soarctl up && soarctl migrate --fresh`
      on a fresh install — `create_all()` now creates it independent of
      `stamp head`/`upgrade head`.
- [x] `42fbd47b0d46` and `3067dea7c75b` use `prefixed()` consistently with
      `ea0bb43fc071` — no migration creates an unprefixed table/index when
      `database.table_prefix` is non-empty.
- [x] Index name is identical between the `create_all()` path (model) and
      the `alembic upgrade head` path (migration) — both resolve
      `f"ix_{prefixed('workflow_jobs')}_pending_triggered_at"`.
- [x] `deploy/stage` (`table_prefix: "stage_"`) — `alembic upgrade head`,
      if ever run instead of `--fresh`, now applies DDL to
      `stage_audit_log`/`stage_workflow_jobs`, not bare names.
- [x] `docs/concepts/UPGRADE-v2.md` P14 and
      `docs/compose/specs/2026-07-27-sql-job-queue-design.md` [S5] updated.

## Notes

- `ea0bb43fc071_initial_auth_and_jobs_tables.py` was not touched, per the
  spec ([S2.3]) — it already used `prefixed()`/`fk()` throughout.
- The spec's design doc itself did not yet exist on any git branch (it
  had been authored directly in the shared checkout outside version
  control); it is added to this worktree/branch as part of this commit
  so the spec → plan → report chain is preserved on this branch.
