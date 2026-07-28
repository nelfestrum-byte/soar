# Report: Connector Config Diff — Redact Unchanged Context Lines (B2)

Spec: `docs/compose/specs/2026-07-28-connector-diff-redaction-fix-design.md`
Plan: `docs/compose/plans/2026-07-28-connector-diff-redaction-fix.md`

## Summary

`GET /connectors/{name}/config/diff` is exposed to `viewer`, the lowest
read-only role (`_RO`). Its redaction relied on `_DIFF_KV_RE`
(`orchestrator/api/connectors.py`), whose first capture group only accepted
`+`/`-` as the leading character of a diff line. In a unified diff, lines
that are unchanged between the two compared revisions but fall inside a
hunk's context window (default 3 lines) start with a plain space, not `+`/
`-`. A hidden field (e.g. `password`) sitting next to an edited non-hidden
field (e.g. `base_url`) in the same `instances.<id>` block would appear as a
context line and skip the regex entirely, so `_redact_diff()` passed it
through unmasked — the secret leaked in plaintext to any `viewer`.

## Changes

- `orchestrator/api/connectors.py:34` — widened `_DIFF_KV_RE`'s first
  capture group from `[+-]` to `[+\- ]` so context lines (leading space)
  match the same as `+`/`-` lines:

  ```python
  _DIFF_KV_RE = re.compile(r"^([+\- ])(\s*)([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
  ```

  `_redact_diff()` needed no change — it already reconstructs the output
  line from `match.group(1)`, so capturing a space there restores the
  correct context prefix automatically. The `+++`/`---` file-header guard
  above the regex call is untouched and still short-circuits before this
  line is ever reached for those two lines.
- `tests/orchestrator/api/test_connectors_api.py` — new
  `test_config_diff_redacts_unchanged_hidden_field_context_line`: saves a
  config with `host`+`password`, changes only `host` across two commits,
  requests `/config/diff` as `viewer`, and asserts the secret value never
  appears in the response while `********` does. Confirmed failing against
  the unfixed regex (secret value visible in the diff) before applying the
  one-line fix, then passing after.
- `docs/agents/security-patterns.md` — tightened the connector secret
  redaction paragraph (D1): it now says masking in `/config/diff` covers
  both the edited (`+`/`-`) lines and unchanged context lines around them,
  which is what B2 actually fixed.

No other files changed for B2. `_redact_yaml()` (used by `GET /config` and
`/config/history/{commit}`) parses YAML structurally rather than diff text
and was never affected by this bug (per spec [S3]).

## Prerequisite worktree sync

Per the task instructions, this worktree was created from an older snapshot
of `main` and was missing two previously-merged fixes (S7/S8) that also
touched files this task depends on:

- `orchestrator/api/connectors.py` — synced verbatim from the shared
  checkout as instructed. Verified `HIDDEN_FIELDS: ClassVar[set[str]] =
  set()` is present in `CONNECTOR_TEMPLATE` (grep result below) before
  starting B2 work.
- `soar/tools/openapi.py` — also stale (same S7/S8 fixes: hidden-field
  auto-detection on generated connectors, and the generated config's
  instance key using the connector name instead of `{ClassName}1`). This
  file wasn't in the explicit sync instructions, but its staleness was the
  cause of a pre-existing full-suite failure
  (`tests/soar/tools/test_openapi.py::test_generate_config`), so it was
  synced the same way to restore the "fully green before and after" baseline
  the task required. One resulting stale assertion in
  `tests/orchestrator/api/test_connectors_api.py::test_generated_connector_config`
  (`"GenConfigTestConnector1:"` → `"gen_config_test:"`) was updated to match,
  mirroring the equivalent test on the current `main`.

## Testing

```
python -m pytest tests/orchestrator/api/test_connectors_api.py -v
40 passed, 4 warnings in 6.62s
```

Full suite:

```
python -m pytest tests/ -q
688 passed, 1 skipped, 13 warnings in 73.66s
```

Zero failures before (after the prerequisite sync) and after the B2 fix —
no new regressions, no pre-existing failures left open.

## Success criteria (spec S5)

- [x] `password`/`api_key`/any `HIDDEN_FIELDS` field never appears in
      `/config/diff` output unmasked — neither on a `+`/`-` line nor a
      context line
- [x] The fact that a hidden field changed (which field, `+`/`-` or not)
      stays visible — only the value is masked, not the diff structure
- [x] Regression test on the already-covered case (`+`/`-` hidden field,
      `test_config_history_and_diff_mask_hidden_field`) stays green
- [x] `docs/agents/security-patterns.md` updated alongside this fix (D1)
