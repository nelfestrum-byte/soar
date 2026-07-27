# Plan: Connector Config Schema + Secret Field Redaction

Spec: `docs/compose/specs/2026-07-27-connector-secrets-schema-design.md`

## introspect.py

- [ ] Add failing test `test_fields_extracts_types_and_defaults` (str/int/bool/no-default) to `tests/orchestrator/core/test_introspect.py`
- [ ] Add failing test `test_hidden_fields_from_class_attribute` (class with `HIDDEN_FIELDS`, class without)
- [ ] Add `_target_name`, `_fields`, `_hidden_fields` to `orchestrator/core/introspect.py`
- [ ] `parse_classes` includes `"fields"` and `"hidden_fields"` keys without breaking existing `/describe` consumers
- [ ] Confirm existing `test_introspect.py` tests still pass unchanged

## connectors.py

- [ ] Add failing tests to `tests/orchestrator/api/test_connectors_api.py`:
  - `GET /{name}/schema` returns typed fields with `hidden: true` on password/api_key-like field
  - `GET /config` masks hidden field value for viewer AND admin
  - `GET /config/history/{commit}` masks hidden field value from an old commit
  - `GET /config/diff` masks hidden field value in diff output, still shows the line changed
  - `PUT /config` merge-on-write: submitting `********` keeps old secret on disk
  - `PUT /config` real hidden-field change: `agent` gets 403, `admin` succeeds
  - `PUT /config` non-hidden field change: both `agent` and `admin` succeed as before
- [ ] Add `_connector_py_path`, `_hidden_fields_for`, `_MASK`, `_redact_yaml`, `_redact_diff`, `_merge_hidden_fields` helpers
- [ ] New `GET /{name}/schema` route (`_RO`)
- [ ] Redact in `GET /config`, `/config/history/{commit}`; line-redact in `/config/diff`
- [ ] `PUT /config`: merge-on-write + manual `admin`-only check for real hidden-field changes
- [ ] Confirm all existing `test_connectors_api.py` tests still pass unchanged

## Connectors: HIDDEN_FIELDS

Verified against actual `__init__` signatures (not just `*.example.yml`):

- [ ] elastic: `password`, `api_key`
- [ ] ssh: `password`
- [ ] active_directory: `bind_password`
- [ ] freeipa: `password` (constructor has no `bind_password` field, unlike spec table)
- [ ] security_onion: `password` (constructor has no `api_key` field, unlike spec table)
- [ ] wazuh: `password`
- [ ] postgresql: `password`
- [ ] mysql: `password`
- [ ] mssql: `password`
- [ ] virus_total: `api_key`
- [ ] abusech: none (constructor takes only `instance_name`, unlike spec table)
- [ ] smtp: `password`
- [ ] telegram: `token` (constructor field is `token`, not `bot_token`)
- [ ] winrm: `password`
- [ ] smb_rpc: `password`
- [ ] shodan: `api_key`
- [ ] fofa: `api_key`
- [ ] censys: `api_secret` (constructor has `api_id`/`api_secret`, no `api_key` field)
- [ ] misp: `api_key`
- [ ] rstcloud: `api_key`
- [ ] kaspersky_opentip: `api_key`
- [ ] urlhaus: none
- [ ] crtsh: none
- [ ] file: none

## UI

- [ ] `ui/src/api.js`: add `getConnectorSchema(name)`
- [ ] `ui/src/views/Connectors.vue`: schema-driven form per [S7], raw-textarea fallback when schema empty

## Verification

- [ ] `python -m pytest` — full suite green
- [ ] Write report at `docs/compose/reports/connector-secrets-schema.md`
