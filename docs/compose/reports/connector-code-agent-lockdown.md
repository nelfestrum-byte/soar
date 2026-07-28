# Report: `PUT /connectors/{name}/code` — Literal `admin` Only (B3)

Spec: `docs/compose/specs/2026-07-28-connector-code-agent-lockdown-design.md`
Plan: `docs/compose/plans/2026-07-28-connector-code-agent-lockdown.md`

## Summary

`GET /config`/`/config/history[/{commit}]`/`/config/diff` redact hidden
fields based purely on parsing `HIDDEN_FIELDS` out of a connector's own
`.py` file (`_hidden_fields_for()`). `PUT /connectors/{name}/code` — the
route that writes that same file — was on `require_role(*_ADMIN)`, where
`_ADMIN = ("admin", "agent")`. That let `agent` overwrite a connector's
code without its `HIDDEN_FIELDS` declaration, silently disabling secret
redaction for that connector, then read the now-unmasked value back via
`GET /config` — a two-request path around the write-only secrets model.

## Changes

- `orchestrator/api/connectors.py` — `save_connector_code`
  (`PUT /{name}/code`) now depends on `require_role("admin")` (a literal,
  not `*_ADMIN`), the same pattern already used for `/auth/*`,
  `/audit-log`, `/transfer/*`, `PUT /prompts/user`. No other route
  changed:
  - `restore_connector_code` (`POST /{name}/code/restore`) stays on
    `*_ADMIN` deliberately — restore only replays an already-existing
    git-history version; every version in that history was itself written
    through `PUT` (now admin-only), so restore can't introduce a version
    with a weakened `HIDDEN_FIELDS` that wasn't already admin-approved.
  - `save_connector_config` (`PUT /{name}/config`) is untouched — it
    already does its own field-level `admin`-only check for hidden-field
    changes inside the handler body, independent of this route-level fix.
  - `create_connector`/`delete_connector` are untouched — `agent` can
    still create/delete a connector (the template stub has no secrets to
    protect), just not overwrite an existing connector's code.
- `tests/orchestrator/api/test_connectors_api.py` — new
  `test_agent_forbidden_from_connector_code_write` (confirmed `403` for
  `agent`, and that the on-disk file still has its original
  `HIDDEN_FIELDS`) and `test_admin_can_write_connector_code_after_lockdown`
  (regression: `admin` unaffected).
- `tests/orchestrator/api/test_agent_role_rbac.py` — the existing
  `test_agent_can_write_and_delete_connector_code` encoded the old,
  now-intentionally-wrong behavior (`agent` writes code → `200`) and
  started failing once the fix landed. Split into
  `test_agent_can_create_and_delete_connector` (the `POST`/`DELETE` routes
  this track doesn't touch, still `_ADMIN`) and
  `test_agent_cannot_write_connector_code` (a new explicit-403 case,
  matching this file's own stated convention of covering "the explicit
  403s on routes that intentionally did not" gain `agent`).
- `docs/agents/security-patterns.md` — extended the "Connector secret
  redaction" paragraph (D2): the existing sentence about `agent` getting
  `403` on changing a credential value now also notes `PUT
  /connectors/{name}/code` is admin-only for the same reason
  (`HIDDEN_FIELDS` is the redaction policy itself, not general code
  `agent` should be able to rewrite), and that `restore` deliberately
  stays `_ADMIN`.

## Prerequisite worktree sync

This worktree was created from an older snapshot of `main` and was
missing several previously-merged fixes touching files this task depends
on: `orchestrator/api/connectors.py` (S8's `HIDDEN_FIELDS` on
`CONNECTOR_TEMPLATE`, B2's `_DIFF_KV_RE` widening) and `soar/tools/openapi.py`
plus its test (S7/S8). Synced all of them verbatim from the shared
checkout before starting; verified via `grep` that `CONNECTOR_TEMPLATE`
had `HIDDEN_FIELDS: ClassVar[set[str]] = set()` and `_DIFF_KV_RE` had the
widened `[+\- ]` character class. `docs/agents/security-patterns.md` was
also stale (missing B2's and S3's paragraph updates) and was synced the
same way before layering the D2 addition on top, to avoid clobbering
either.

## Testing

```
python -m pytest tests/orchestrator/api/test_connectors_api.py -v
43 passed, 4 warnings in 6.88s

python -m pytest tests/orchestrator/api/test_agent_role_rbac.py tests/orchestrator/api/test_connectors_api.py -v
70 passed, 4 warnings in 9.80s
```

Full suite:

```
python -m pytest tests/ -q
700 passed, 1 skipped, 13 warnings in 74.38s
```

Zero failures — the pre-existing regression in `test_agent_role_rbac.py`
found along the way was fixed as part of this change, not left open.

## Success criteria (spec S5)

- [x] `PUT /connectors/{name}/code` from `agent` — `403`; from `admin` —
      unaffected (validation, git commit, audit record all still work)
- [x] `agent` cannot weaken/clear a connector's `HIDDEN_FIELDS` through any
      path available to it
- [x] `docs/agents/security-patterns.md` updated alongside this fix (D2)
