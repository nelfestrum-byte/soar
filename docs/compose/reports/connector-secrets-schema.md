# Report: Connector Config Schema + Secret Field Redaction

Spec: `docs/compose/specs/2026-07-27-connector-secrets-schema-design.md`
Plan: `docs/compose/plans/2026-07-27-connector-secrets-schema.md`

## Summary

`GET /connectors/{name}/config` and its history/diff variants leaked connector
secrets (passwords, API keys) in plaintext to every RBAC role, including
`viewer`, and `PUT` allowed the low-privilege `agent` role to overwrite
secrets. Implemented per spec:

1. Extended AST-based `parse_classes()` (`orchestrator/core/introspect.py`)
   to extract typed constructor fields (`_fields()`) and a per-connector
   `HIDDEN_FIELDS: ClassVar[set[str]]` declaration (`_hidden_fields()`) —
   both parsed via AST, no import of connector modules.
2. New `GET /connectors/{name}/schema` endpoint (`_RO`) returning
   `{"fields": [{name, type, default, hidden}, ...]}`.
3. Redaction (`"********"`) applied in `GET /config`, `/config/history/
   {commit}`, and line-by-line in `/config/diff` — for **all** roles,
   including `admin` (write-only secrets).
4. `PUT /config`: merge-on-write (a submitted `********` keeps the on-disk
   value) plus a field-level RBAC split — only the literal `admin` role may
   set a hidden field to a real new value; `agent` gets `403`. Non-hidden
   fields are unaffected (both roles can still edit them, as before).
5. All 24 connectors under `soar/connectors/` got an explicit `HIDDEN_FIELDS`
   class attribute, verified against actual `__init__` signatures (not just
   `*.example.yml`) — several corrections were needed vs. the spec's S8
   table (see below).
6. `ui/src/views/Connectors.vue` (`ui/` is a manual-testing stand, not part
   of the product) replaced the raw config textarea with a schema-driven
   form: hidden fields render as always-empty password inputs, disabled for
   non-admin, and are omitted from the save payload when left blank; falls
   back to the raw textarea when `GET /schema` returns no fields.

## Corrections to the spec's S8 table (verified against real `__init__`)

- `freeipa`: constructor field is `password`, not `bind_password`.
- `security_onion`: constructor has no `api_key` field — only `password`.
- `abusech`: constructor takes only `instance_name` — no credential fields
  at all (declared `HIDDEN_FIELDS: ClassVar[set[str]] = set()`).
- `telegram`: constructor field is `token`, not `bot_token`.
- `censys`: constructor has `api_id`/`api_secret`, no `api_key` field —
  hidden field is `api_secret` (`api_id` is not secret).

## Files changed

- `orchestrator/core/introspect.py` — `_fields`, `_target_name`,
  `_hidden_fields`; `parse_classes()` now includes `"fields"` and
  `"hidden_fields"` keys (additive, doesn't break `/describe`).
- `orchestrator/api/connectors.py` — `_connector_py_path`,
  `_hidden_fields_for`, `_redact_yaml`, `_redact_diff`,
  `_merge_hidden_fields` helpers; new `GET /{name}/schema` route; redaction
  wired into `GET /config`, `/config/history/{commit}`, `/config/diff`;
  merge-on-write + admin-only hidden-field check wired into `PUT /config`.
- `soar/connectors/*/*.py` (24 files) — `HIDDEN_FIELDS: ClassVar[set[str]]`
  added to every connector class (see table above for corrections).
- `ui/src/api.js` — added `getConnectorSchema(name)`.
- `ui/src/views/Connectors.vue` — schema-driven config form per [S7], raw
  textarea fallback preserved.
- `tests/orchestrator/core/test_introspect.py` — `_fields()`/
  `_hidden_fields()` unit tests (typed defaults, `HIDDEN_FIELDS` present/
  absent).
- `tests/orchestrator/api/test_connectors_api.py` — schema endpoint test,
  404 test, redaction tests (admin + viewer, history, diff), merge-on-write
  test, RBAC split tests (`agent` 403 / `admin` 200 on hidden field change,
  both roles OK on non-hidden field change).

## Testing

Tests were added first and confirmed failing against the pre-change code
(schema endpoint 404, secrets visible in `GET /config`, no RBAC split on
`PUT /config`), then made to pass by the implementation.

Full suite: `python -m pytest`

```
608 passed, 1 skipped, 4 failed
```

The 4 failures are pre-existing and unrelated to this change (confirmed via
`git stash` + re-run on the unmodified tree, same 4 failures):

- `tests/orchestrator/test_redis_integration.py::test_redis_integration_*`
  (3 tests) — require a live Redis server on `localhost:6379`, not available
  in this sandbox.
- `tests/soar/tools/test_openapi.py::test_generate_config` — pre-existing
  bug in `soar/tools/openapi.py`'s `_generate_config` (uses the class name
  as the instance key instead of the requested connector name); unrelated
  to `soar/connectors/` or `orchestrator/api/connectors.py`.

All 39 tests in `tests/orchestrator/api/test_connectors_api.py` (7 new) and
all 7 tests in `tests/orchestrator/core/test_introspect.py` (4 new) pass.

## Success criteria (spec S10)

- [x] `GET /connectors/{name}/schema` returns typed fields with `hidden: bool`
- [x] `GET /config`, `/config/history[/{commit}]` never return a hidden
      field's real value to any role, including `admin`
- [x] `/config/diff` shows the fact of a hidden-field change, not the value
- [x] `PUT /config` rejects `agent` changing a hidden field (`403`), allows
      `admin`; non-hidden fields still writable by both
- [x] Merge-on-write doesn't clobber an existing secret when the form is
      saved with an empty hidden field
- [x] All 24 connectors got `HIDDEN_FIELDS`; no existing connector test broke
- [x] `Connectors.vue` — schema-driven form, hidden fields as password
      inputs, `disabled` for non-admin, never prefilled
- [x] Raw-textarea fallback works for connectors without a schema
