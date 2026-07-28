# Plan: Pending-Index on Fresh Installs + Migration `table_prefix` Fix

Spec: `docs/compose/specs/2026-07-28-workflow-jobs-index-table-prefix-design.md`

## Tests first (fail before implementation)

- [x] `tests/orchestrator/store/test_job_record_index.py` (new file — named
      to avoid a basename collision with the existing
      `tests/orchestrator/test_models.py`, both dirs lack `__init__.py`):
      add `test_create_all_creates_pending_index` — `Base.metadata.create_all()`
      against a sync SQLite engine, query `sqlite_master` for
      `type='index'`, assert `ix_workflow_jobs_pending_triggered_at` exists
      (empty `table_prefix`, matches default test config)
- [x] `tests/orchestrator/test_alembic_schema.py`: add
      `test_alembic_upgrade_head_respects_table_prefix` — write a
      `config.yaml` with `database.table_prefix: "test_"`, run
      `alembic upgrade head` as a subprocess (same pattern as the existing
      `test_alembic_upgrade_head_matches_orm_metadata`), reflect the
      resulting SQLite schema, assert every table name is prefixed
      (`test_workflow_jobs`, `test_audit_log`, `test_users`, ...) and no
      bare/unprefixed table/index exists
- [x] Confirm both new tests fail against current code (index test: no
      `Index` on `JobRecord` yet; prefix test: `3067dea7c75b` and
      `42fbd47b0d46` still use literal names) — confirmed, both failed
      before implementation

## Implementation

- [x] `orchestrator/store/models.py`: add
      `Index(f"ix_{prefixed('workflow_jobs')}_pending_triggered_at",
      "status", "triggered_at", postgresql_where=text("status = 'PENDING'"),
      sqlite_where=text("status = 'PENDING'"))` to `JobRecord.__table_args__`;
      import `Index`/`text` from `sqlalchemy`; replace the "not declared
      here" comment (no longer accurate)
- [x] `alembic/versions/42fbd47b0d46_add_workflow_jobs_pending_index.py`:
      import `prefixed` from `orchestrator.db.base`; index name becomes
      `f"ix_{prefixed('workflow_jobs')}_pending_triggered_at"` (must match
      the model's index name exactly — same name, two creation paths);
      table name via `prefixed("workflow_jobs")` in both `upgrade()`/
      `downgrade()`; correct the module docstring — `ea0bb43fc071` already
      uses `prefixed()` correctly (docstring currently claims otherwise);
      note that `3067dea7c75b` is fixed in this same change, not left as
      precedent
- [x] `alembic/versions/3067dea7c75b_add_audit_log_table.py`: replace
      literal `'audit_log'` with `prefixed('audit_log')` in
      `create_table`/`create_index`/`drop_index`/`drop_table`; replace
      `op.f('ix_audit_log_*')` with `f"ix_{prefixed('audit_log')}_*"` to
      match the naming convention already used in `ea0bb43fc071`; import
      `prefixed`
- [x] Do not touch `ea0bb43fc071_initial_auth_and_jobs_tables.py` or any
      `revision`/`down_revision` identifiers anywhere

## Verification

- [x] `python -m pytest tests/orchestrator/store/ -v`
- [x] `python -m pytest tests/orchestrator/test_alembic_schema.py -v`
- [x] `python -m pytest tests/ -q` — confirm the only failure is the
      known pre-existing `tests/soar/tools/test_openapi.py::test_generate_config`
      (688 passed, 1 skipped, 1 failed — matches expectation, zero new
      failures)

## Docs

- [x] `docs/concepts/UPGRADE-v2.md` P14 — note the partial index is now
      guaranteed on any install path (fresh `create_all()` or
      `upgrade head`), not just upgrade
- [x] `docs/compose/specs/2026-07-27-sql-job-queue-design.md` [S5] — same
      update (D8): index no longer migration-only
- [x] `docs/compose/reports/workflow-jobs-index-table-prefix.md` after
      implementation
