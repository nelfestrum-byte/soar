# Plan: `/transfer/export` + `/transfer/import` Hardening (S3)

Spec: `docs/compose/specs/2026-07-28-transfer-export-import-hardening-design.md`

## Tests first (`tests/orchestrator/api/test_transfer_api.py`)

- [x] Fix `sample_archive` fixture: `connectors/test_connector/code.py` and
      `workflows/test_workflow.py` content must inherit from
      `BaseConnector`/`BaseWorkflow` (by name, AST-checked) so existing
      round-trip/conflict tests stay green once validation is wired in
- [x] New `test_export_redacts_hidden_fields` — connector with
      `HIDDEN_FIELDS = {"password"}` and a real value on disk; `/export`;
      unzip; `connectors/{name}/config.yml` inside contains `********`, not
      the real value
- [x] New `test_export_writes_audit_log` — `/export`; `audit_log` has a
      `transfer.export` row with correct `actor_id`/`resource_type`
- [x] New `test_import_writes_audit_log` — `/import?force=true` with a valid
      archive; `audit_log` has a `transfer.import` row
- [x] New `test_import_conflicts_no_audit_log` — `/import` without `force`
      hitting conflicts; no `transfer.import` row written
- [x] New `test_import_rejects_invalid_workflow_code` — archive with
      `workflows/{name}.py` not inheriting a known workflow base → `422`;
      confirm the workflow file was never written to disk
- [x] New `test_import_rejects_invalid_connector_code` — same for connector
      code not inheriting `BaseConnector`
- [x] Confirm existing tests (`test_export_returns_zip`,
      `test_import_returns_conflicts`, `test_import_with_force`,
      `test_import_invalid_file`) still pass unchanged in behavior

## Implementation (`orchestrator/api/transfer.py`)

- [x] Import `_hidden_fields_for`/`_redact_yaml` from
      `orchestrator/api/connectors.py` (reuse, no duplicate helpers)
- [x] Import `validate_connector_code`/`validate_action_code`/
      `validate_workflow_code` from `orchestrator/api/validation.py`
- [x] Import `orchestrator.audit.service as audit_service`,
      `CurrentUser`/`require_role` from `orchestrator.auth.dependencies`,
      `get_db`/`AsyncSession` for the `db` dependency
- [x] `export_entities`: add `user`/`db` params; redact each connector's
      `.yml` via `_redact_yaml(content, _hidden_fields_for(config, name))`
      before `zf.writestr` (switch that one write from `zf.write` to
      `zf.writestr` on the read+redacted string; `.py` files and
      actions/workflows keep `zf.write` as-is — no secrets there)
- [x] `export_entities`: `audit_service.record(..., action="transfer.export",
      resource_type="transfer", resource_id=filename, detail={connectors,
      actions, workflows})` after the archive is built, before returning
      the `StreamingResponse`
- [x] `import_entities`: add `user`/`db` params
- [x] `import_entities`: keep the conflict-preflight early `return` exactly
      as-is (no audit call on that path — nothing changed on disk)
- [x] `import_entities`: after the early-return branch, before any
      `zf.extract`/`shutil.move` — validate every `.py` entry present in
      the manifest (`validate_connector_code`, `validate_action_code(...,
      name)`, `validate_workflow_code`) reading bytes straight from the
      still-open `zf`; a validation failure raises `HTTPException(422)`
      before any file touches disk
- [x] `import_entities`: after each successful `shutil.move` — `git.commit`
      the relative path (`connectors/{name}/{name}.py`,
      `connectors/{name}/{name}.yml`, `actions/{name}.py`,
      `workflows/{name}.py`) with message `f"Import {type} {name}"`,
      `author_name, author_email = audit_service.git_author(user)`; catch
      `RuntimeError` per-file into a `warnings` list, don't abort the loop
- [x] `import_entities`: `audit_service.record(..., action="transfer.import",
      resource_type="transfer", resource_id=file.filename or "",
      detail={imported, conflicts_overwritten})` after the reload block,
      before the final `return`; include `warnings` in the response only
      when non-empty

## Verification

- [x] `python -m pytest tests/orchestrator/api/test_transfer_api.py -v` — all green
- [x] `python -m pytest tests/ -q` — only pre-existing
      `tests/soar/tools/test_openapi.py::test_generate_config` failure, zero
      new failures
- [x] Write report `docs/compose/reports/transfer-export-import-hardening.md`
- [x] Update `docs/agents/security-patterns.md` (D1): note write-only
      secrets model now also covers `/transfer/export`
- [x] Update `AGENTS.md` (D3): note `/transfer/*` is now covered by audit
      trail (do not claim `POST /jobs`/`POST /webhooks/{name}` are covered)
