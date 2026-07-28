# Report: New Connectors Get `HIDDEN_FIELDS` by Default (S8)

Spec: `docs/compose/specs/2026-07-28-new-connector-hidden-fields-default-design.md`
Plan: `docs/compose/plans/2026-07-28-new-connector-hidden-fields-default.md`

## Summary

Neither of the two connector-creation paths declared `HIDDEN_FIELDS` on the
generated class, so secret redaction (P13,
`connector-secrets-schema-design.md`) silently became a no-op for every new
connector until someone remembered to add the attribute by hand. Fixed both
paths:

1. `CONNECTOR_TEMPLATE` (`orchestrator/api/connectors.py`), used by
   `POST /connectors/{name}` and `GET /connectors/template` for manual
   connector creation, now imports `ClassVar` and declares
   `HIDDEN_FIELDS: ClassVar[set[str]] = set()` on the generated class. This is
   an ergonomic fix, not a technical guarantee — the template still can't know
   what fields the author will add to `__init__`, but the visible empty
   declaration makes it more likely the author fills it in when adding a
   secret parameter, rather than forgetting the attribute exists at all.
2. `OpenAPIGenerator._extract_security()` (`soar/tools/openapi.py`) now also
   collects a `hidden_fields` set alongside the existing `params`/`fields`/
   `header_setup` building: the apiKey scheme's param name, `"token"` for
   bearer, `"password"` (not `"username"`) for basic. `_generate_class()`
   renders this as a real `HIDDEN_FIELDS: ClassVar[set[str]] = {...}` line
   (sorted, `set()` when empty) in the generated class — a technical fix,
   since the generator already knows the exact auth field names it's putting
   into `__init__`.

`username` in a `basic` scheme is deliberately excluded from `hidden_fields`,
matching the existing convention across built-in connectors (e.g.
`elastic_basic`, where `username` is shown in the example config in plaintext
and only `password` is masked).

OAuth2 schemes are unaffected — the generator doesn't add any field to
`__init__` for them today (only a warning + a `config_lines` comment
requiring manual implementation), so there's nothing to declare as hidden;
if a human later hand-writes the OAuth2 field, they hand-write
`HIDDEN_FIELDS` too, same as the manual-template path.

## Files changed

- `orchestrator/api/connectors.py` — `CONNECTOR_TEMPLATE`: added
  `from typing import ClassVar` and `HIDDEN_FIELDS: ClassVar[set[str]] =
  set()`.
- `soar/tools/openapi.py` — `_extract_security()`: added `"hidden_fields":
  set()` to the result dict, populated from apiKey/bearer/basic schemes.
  `_generate_class()`: added `from typing import ClassVar` import to the
  generated module and a `HIDDEN_FIELDS: ClassVar[set[str]] = {hidden_repr}`
  class attribute line, computed from `sec["hidden_fields"]`.
- `tests/orchestrator/api/test_connectors_api.py` — new
  `test_connector_template_has_hidden_fields`.
- `tests/soar/tools/test_openapi.py` — new
  `test_extract_security_hidden_fields_api_key`,
  `test_extract_security_hidden_fields_bearer`,
  `test_extract_security_hidden_fields_basic`,
  `test_extract_security_no_hidden_fields`,
  `test_generate_class_hidden_fields_api_key`,
  `test_generate_class_hidden_fields_bearer`,
  `test_generate_class_hidden_fields_basic`,
  `test_generate_class_no_security_empty_hidden_fields`.

Note: this worktree's copy of `soar/tools/openapi.py` and
`tests/orchestrator/api/test_connectors_api.py` was on a pre-S7 snapshot
(`_generate_config` still keyed the example YAML instance by class name
instead of the connector name); both were brought up to date with `main`
before this track's changes, as instructed, and that sync is not part of
this feature's diff.

## Testing

New tests were added first and confirmed failing against the pre-change code
(9 failures: 1 in `test_connectors_api.py`, 8 in `test_openapi.py`), then made
to pass by the implementation.

```
tests/orchestrator/api/test_connectors_api.py tests/soar/tools/test_openapi.py
74 passed
```

Full suite:

```
python -m pytest tests/ -q
696 passed, 1 skipped, 13 warnings
```

0 failed, both before (pre-existing baseline in this worktree, confirmed via
targeted runs) and after this change — no regressions.

## Success criteria (spec S4)

- [x] `CONNECTOR_TEMPLATE` declares `HIDDEN_FIELDS: ClassVar[set[str]] =
      set()` — present in any manually created connector from the first
      commit
- [x] `OpenAPIGenerator` automatically fills `HIDDEN_FIELDS` from
      `apiKey`/`bearer`/`basic` schemes in `securitySchemes`, no human
      involvement
- [x] `username` in a `basic` scheme is excluded from `HIDDEN_FIELDS` —
      consistent with the convention on existing connectors
- [x] `GET /connectors/{name}/schema` for a generated connector immediately
      returns the correct `hidden: bool` with no manual code edit (schema
      endpoint reads `HIDDEN_FIELDS` via AST, already covered by P13's
      `_hidden_fields()`; this track supplies the attribute it reads)
- [x] Existing `test_openapi.py`/`test_connectors_api.py` tests unaffected
