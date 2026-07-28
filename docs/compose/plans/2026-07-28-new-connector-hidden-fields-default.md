# Plan: New Connectors Get `HIDDEN_FIELDS` by Default (S8)

Spec: `docs/compose/specs/2026-07-28-new-connector-hidden-fields-default-design.md`

## `orchestrator/api/connectors.py` — `CONNECTOR_TEMPLATE`

- [ ] Add failing test `test_connector_template_has_hidden_fields` to
      `tests/orchestrator/api/test_connectors_api.py` — `GET /connectors/template`
      response `code` contains `HIDDEN_FIELDS: ClassVar[set[str]] = set()`
- [ ] Update `CONNECTOR_TEMPLATE` ([S2.1]): add `from typing import ClassVar`
      import and `HIDDEN_FIELDS: ClassVar[set[str]] = set()` class attribute
- [ ] Confirm existing `test_connector_template`, `test_connector_template_custom`,
      `test_create_connector*` tests still pass unchanged

## `soar/tools/openapi.py` — `_extract_security` + `_generate_class`

- [ ] Add failing tests to `tests/soar/tools/test_openapi.py`:
  - `test_extract_security_hidden_fields_api_key` — `SPEC_API_KEY_HEADER` →
    `sec["hidden_fields"] == {"X-API-Key"}`
  - `test_extract_security_hidden_fields_bearer` — `SPEC_BEARER` →
    `sec["hidden_fields"] == {"token"}`
  - `test_extract_security_hidden_fields_basic` — `SPEC_BASIC` →
    `sec["hidden_fields"] == {"password"}` (not `"username"`)
  - `test_extract_security_no_hidden_fields` — `MINIMAL_SPEC` →
    `sec["hidden_fields"] == set()`
  - `test_generate_class_hidden_fields_api_key` — generated code contains
    `HIDDEN_FIELDS: ClassVar[set[str]] = {"X-API-Key"}`
  - `test_generate_class_hidden_fields_bearer` — generated code contains
    `HIDDEN_FIELDS: ClassVar[set[str]] = {"token"}`
  - `test_generate_class_hidden_fields_basic` — generated code contains
    `{"password"}`, not `"username"`
  - `test_generate_class_no_security_empty_hidden_fields` — no securitySchemes
    → generated code contains `HIDDEN_FIELDS: ClassVar[set[str]] = set()`
- [ ] `_extract_security()`: add `"hidden_fields": set()` to `result` dict;
      populate with apiKey `param_name`, bearer `"token"`, basic `"password"`
      (not `"username"`) per [S2.2]
- [ ] `_generate_class()`: compute `hidden_repr` from `sec["hidden_fields"]`
      (sorted, `set()` when empty), add `from typing import ClassVar` import
      and `HIDDEN_FIELDS: ClassVar[set[str]] = {hidden_repr}` line to the
      generated class body
- [ ] Confirm existing `test_extract_api_key_header`, `test_extract_bearer`,
      `test_extract_basic`, `test_extract_no_security`,
      `test_generate_class_has_required_parts`, `test_generate_class_with_auth`,
      `test_generate_config*`, `test_generate_creates_files` still pass
      unchanged (`.example.yml` output is untouched by this track)

## Verification

- [ ] `python -m pytest tests/orchestrator/api/test_connectors_api.py tests/soar/tools/test_openapi.py -v`
- [ ] `python -m pytest tests/ -q` — full suite green, 0 failed, no new failures
      vs. pre-change baseline (743 passed, 1 skipped)
- [ ] Write report at `docs/compose/reports/new-connector-hidden-fields-default.md`
