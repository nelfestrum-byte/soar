# Report: `/transfer/export` + `/transfer/import` Hardening (S3)

Spec: `docs/compose/specs/2026-07-28-transfer-export-import-hardening-design.md`
Plan: `docs/compose/plans/2026-07-28-transfer-export-import-hardening.md`

## Summary

`orchestrator/api/transfer.py` had three gaps relative to the rest of the
API (BAGFIX_PLAN S3): `POST /transfer/export` shipped connector secrets in
plaintext inside the archive, neither `/export` nor `/import` wrote to
`audit_log`, and `/import` wrote extracted `.py` files straight to disk
without running them through the same `validate_*_code` checks as `PUT
/code`, and without a `git.commit()` — so imported code/config had no git
history and could bypass the class-inheritance check entirely. Implemented
per spec:

1. **Export redaction** — the connector `.yml` write switched from
   `zf.write` (raw file bytes) to `zf.writestr` on content read, redacted
   via the existing `_redact_yaml`/`_hidden_fields_for` (imported from
   `orchestrator/api/connectors.py`, not duplicated), and re-serialized.
   `.py` files and actions/workflows are unaffected — no secrets there, so
   they keep `zf.write` as before. This extends the P13 write-only-secrets
   model (secrets settable, never readable via API) to `/export`: a secret
   that can't be read via `GET /config` can't be read via `/export` either.
2. **Audit logging** — both routes gained explicit `user`/`db` params
   (the router only had `dependencies=[Depends(require_role("admin"))]`,
   which doesn't expose `CurrentUser` inside the function body) and call
   `audit_service.record(...)`: `transfer.export` after the archive is
   built (before the `StreamingResponse`), `transfer.import` after the
   registry reload (before the final return). `detail` carries only entity
   names (`connectors`/`actions`/`workflows` lists, `imported`/
   `conflicts_overwritten`), never file contents. The conflict-preflight
   early `return` (no `force`, conflicts present) is untouched and does
   **not** audit-log — nothing changed on disk on that path.
3. **Import validation** — a new loop runs immediately after the
   conflict/force check and before any `zf.extract`/`shutil.move`: every
   `.py` entry present in the manifest is read from the still-open `zf` and
   passed to `validate_connector_code`/`validate_action_code(..., name)`/
   `validate_workflow_code` (all already existed in
   `orchestrator/api/validation.py`, reused unmodified). Any failure raises
   `HTTPException(422)` before a single file touches disk — the whole
   import rejects atomically, matching the "validate everything first"
   variant the spec called out as simplest and sufficient.
4. **Import git history** — after each successful `shutil.move`,
   `git.commit()` is called on the relative in-repo path (e.g.
   `connectors/{name}/{name}.py`, `connectors/{name}/{name}.yml`,
   `actions/{name}.py`, `workflows/{name}.py`) with message `f"Import {type}
   {name}"` and `author_name, author_email = audit_service.git_author(user)`
   — the same pattern every other write route in the project uses. A
   `RuntimeError` (the known "nothing to commit" case, e.g. byte-identical
   re-import under `force=true`) is caught per-file into a `warnings` list
   rather than aborting the whole import; the response includes
   `"warnings"` only when non-empty.

## Files changed

- `orchestrator/api/transfer.py` — imports
  (`_hidden_fields_for`/`_redact_yaml` from `connectors.py`,
  `validate_connector_code`/`validate_action_code`/`validate_workflow_code`
  from `validation.py`, `audit_service`, `CurrentUser`, `get_db`); redaction
  in `/export`'s connector `.yml` write; `user`/`db` params + audit calls on
  both routes; pre-write validation loop and per-file `git.commit()` +
  `warnings` collection in `/import`.
- `tests/orchestrator/api/test_transfer_api.py` — `sample_archive` fixture's
  connector/workflow stub code updated to inherit `BaseConnector`/
  `BaseWorkflow` (by name; AST-checked, no import needed for the check
  itself) so the pre-existing round-trip/conflict tests keep passing once
  validation is wired in. New tests: `test_export_redacts_hidden_fields`,
  `test_export_writes_audit_log`, `test_import_writes_audit_log`,
  `test_import_conflicts_no_audit_log` (preflight path writes nothing),
  `test_import_rejects_invalid_connector_code` and
  `test_import_rejects_invalid_workflow_code` (422, and the target
  directory/file is confirmed absent afterward).
- `docs/agents/security-patterns.md` (D1) — noted the write-only secrets
  model now also covers `/transfer/export`.
- `AGENTS.md` (D3) — noted `/transfer/{export,import}` now write
  `audit_log`; explicitly still not `POST /jobs` / `POST /webhooks/{name}`
  (separate in-flight tracks).

## Testing

Tests were written first against the pre-change router (redaction test
would have seen the plaintext secret, audit tests would have found zero
rows, validation-rejection tests would have found `200`/files written),
then made to pass by the implementation.

`tests/orchestrator/api/test_transfer_api.py`:

```
10 passed
```

Full suite: `python -m pytest tests/ -q`

```
1 failed, 692 passed, 1 skipped
```

The one failure, `tests/soar/tools/test_openapi.py::test_generate_config`,
is the pre-existing known failure called out in the task (fixed by a
separate spec, unrelated to `orchestrator/api/transfer.py`) — confirmed as
the only failure both before and after this change, zero new failures
introduced.

## Success criteria (spec S4)

- [x] Exported `{name}.yml` inside the archive contains `********` instead
      of `HIDDEN_FIELDS` values, via the same redaction function as the
      rest of the API (no duplicate copy)
- [x] `/export` and `/import` write `audit_log` with the names of
      exported/imported entities, no file contents
- [x] `/import` rejects (`422`) any entity with invalid code/wrong base
      class before anything is written to disk
- [x] `/import` commits each imported file to git as the acting user;
      history/diff/restore see imported versions
- [x] The conflict preflight response (no `force`) does not create an
      audit-log row
- [x] `docs/agents/security-patterns.md`/`AGENTS.md` updated (D1/D3)
