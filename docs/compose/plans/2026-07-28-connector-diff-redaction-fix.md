# Plan: Connector Config Diff — Redact Unchanged Context Lines (B2)

Spec: `docs/compose/specs/2026-07-28-connector-diff-redaction-fix-design.md`

## connectors.py

- [x] Add failing test `test_config_diff_redacts_unchanged_hidden_field_context_line` to
      `tests/orchestrator/api/test_connectors_api.py`: save config with
      `host` + `password`, change only `host` (leave `password` untouched),
      request `/config/diff` as `viewer` → assert the secret value never
      appears in the response body and `"********"` does appear. Confirm it
      fails against current `_DIFF_KV_RE` (secret leaks via the unchanged
      context line).
- [x] Confirm the existing regression test
      `test_config_history_and_diff_mask_hidden_field` (both diff sides
      changed, `+`/`-` lines) still passes unchanged — it stays as the
      already-covered case.
- [x] Fix `_DIFF_KV_RE` in `orchestrator/api/connectors.py`: widen the first
      capture group from `[+-]` to `[+\- ]` so unified-diff context lines
      (leading space) match too. No other change — `_redact_diff` already
      reconstructs the line from `match.group(1)`.
- [x] New test passes; regression test still passes.

## Verification

- [x] `python -m pytest tests/orchestrator/api/test_connectors_api.py -v` green
- [x] `python -m pytest tests/ -q` — full suite green, no new/pre-existing failures
- [x] Update `docs/agents/security-patterns.md` (D1): the connector secret
      redaction paragraph currently doesn't distinguish changed vs. unchanged
      diff lines — tighten it to say context lines are covered too, now that
      it's actually true. Do not touch `docs/concepts/BAGFIX_PLAN.md`.
- [x] Write report at `docs/compose/reports/connector-diff-redaction-fix.md`
