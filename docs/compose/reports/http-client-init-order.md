# Report: Fix `HttpClient` Singleton Init Order (S2)

Spec: `docs/compose/specs/2026-07-28-http-client-init-order-design.md`
Plan: `docs/compose/plans/2026-07-28-http-client-init-order.md`

## What was built

- `soar/runner.py` (modified) — moved the `_build_cache`/`_build_http_client`/
  `_build_http_client_sync` function definitions and the two call sites
  (`tools.http_client = _build_http_client(config)` /
  `tools.http_client_sync = _build_http_client_sync(tools.http_client)`) to
  run **before** `workflows.init(...)` / `connectors.init(...)` /
  `actions.init(...)`. Function bodies are byte-for-byte unchanged — only the
  call-site position moved, per spec [S2]. A one-line comment above the
  assignment explains *why* the order matters (points at the spec's [S1]).
  Since `*.init()` imports every workflow/action/connector module (including
  user/external ones via `external_dir`), any such module doing a top-level
  `from soar.tools import http_client` now binds to the already-configured
  instance instead of the module's original `HttpClient()` default.

## Decision recorded in the plan

Did not wrap `soar/runner.py`'s top-level init code in an `_init()` function.
The spec's [S3] flagged this as an open question ("решить на этапе плана");
reordering two call sites doesn't need it, and doing so would be an
unrelated refactor of the subprocess entry point per repo rules ("не
рефакторить вне задачи"). Instead, the causal mechanism (import-time `from
X import name` binding) is tested directly against a throwaway
`WorkflowRegistry()` instance and the real `_build_http_client()`/
`tools.http_client` — no subprocess, no mutation of the process-wide
registries other tests depend on.

## Tests

`tests/soar/test_runner.py` (extended, +3 tests):

- `test_from_import_http_client_sees_configured_instance_when_assigned_before_init`
  — assigns a configured `HttpClient` (`default_ttl=999`) to
  `tools.http_client`, *then* runs `WorkflowRegistry().init(external_dir=...)`
  against a `tmp_path` fixture module doing `from soar.tools import
  http_client` at top level. Asserts the fixture's captured reference `is`
  the configured instance — the corrected order.
- `test_from_import_http_client_captures_stale_default_when_assigned_after_init`
  — companion/regression test proving the mechanism is actually
  order-sensitive: runs `.init()` first, *then* reassigns `tools.http_client`.
  Asserts the fixture's captured reference is the stale default, not the
  later-assigned configured instance — pins down exactly the bug in spec
  [S1] so the first test can't be trivially true regardless of order.
- `test_runner_assigns_http_client_before_registry_init` — reads
  `soar/runner.py`'s own source via `inspect.getsource` and asserts the
  `tools.http_client = _build_http_client(config)` line precedes all three
  `*.init(external_dir=` call sites textually. Verified this test fails
  against the pre-fix file (`git stash` of just `soar/runner.py`, rerun) and
  passes after the fix — a real red/green regression guard, not a
  vacuously-true assertion.

## Docs check (spec [S4]/D4)

Checked `AGENTS.md` and `docs/agents/config-reference.md` for any statement
of `runner.py`'s init call order. Neither describes an order between
`http_client` setup and `workflows.init()`/`connectors.init()`/
`actions.init()` — `AGENTS.md` only says `runner.py` "также инициализирует
soar.tools.http_client singleton из SOAR_CONFIG" (still true), and
`soar/tools/__init__.py`'s docstring already promised the post-fix
behavior. No doc changes needed.

## Verification

- `python -m pytest tests/soar/test_runner.py -v` → 11 passed.
- Full suite `python -m pytest tests/ -q` → **689 passed, 1 failed, 1
  skipped**. The one failure,
  `tests/soar/tools/test_openapi.py::test_generate_config`, is the single
  known pre-existing failure unrelated to this work (fixed by a separate
  spec), confirmed present before this change too.

## Files changed

- `soar/runner.py` (modified)
- `tests/soar/test_runner.py` (modified)
- `docs/compose/plans/2026-07-28-http-client-init-order.md` (new)
- `docs/compose/reports/http-client-init-order.md` (this file)

## Worktree sync note

This worktree was created from a snapshot that predated the just-merged S1
fix (`docs/compose/specs/2026-07-28-http-client-sync-facade-design.md`).
Before starting this task, `soar/runner.py`, `soar/tools/__init__.py`, and
`soar/tools/http_client.py` were overwritten from `main` to match the
post-S1 state (the last of the three was also stale — missing
`SyncHttpClient` entirely — though only the first two were flagged in the
task's stated ground truth). The spec file for this task itself
(`docs/compose/specs/2026-07-28-http-client-init-order-design.md`) was also
missing from the worktree (committed on `main`, predates this branch) and
was copied over unmodified before implementation started.
