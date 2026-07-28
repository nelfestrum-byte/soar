# Plan: Fix `HttpClient` Singleton Init Order (S2)

Spec: `docs/compose/specs/2026-07-28-http-client-init-order-design.md`

## Decision (per spec [S3] open question)

Do **not** wrap `soar/runner.py`'s top-level init code in an `_init()`
function — that would be an unrelated refactor of the subprocess entry
point's structure, and the reorder itself doesn't need it. Instead, test
the actual causal mechanism (module-level `from X import name` binds at
import time to whatever `X.name` currently is) directly: a fresh
`WorkflowRegistry()` instance + the real `_build_http_client()` +
`tools.http_client` module attribute, exercising the exact same
import-time binding that a real workflow/action/connector module would
hit, without spinning up a subprocess or touching the process-wide
registries used by other tests.

## Tests first (`tests/soar/test_runner.py`)

- [ ] New test: build a configured `HttpClient` via `runner._build_http_client(...)`
      with a distinguishing `default_ttl`, assign it to `tools.http_client`
      (via `monkeypatch.setattr`, auto-restored), *then* call
      `WorkflowRegistry().init(external_dir=...)` against a `tmp_path`
      fixture `.py` file that does `from soar.tools import http_client` at
      module top level and stashes it as a class attribute. Assert the
      stashed reference `is` the configured instance (same object, matching
      `default_ttl`) — proves "assign before init" makes `from ... import`
      see the real instance.
- [ ] Companion regression test: same fixture module (different filename),
      but call `WorkflowRegistry().init(...)` *before* reassigning
      `tools.http_client`. Assert the stashed reference is the *original*
      default instance, not the later-assigned configured one — proves the
      mechanism actually depends on ordering (i.e. the first test isn't
      trivially true regardless of order), pinning down exactly the bug
      described in spec [S1].
- [ ] Confirm both tests behave as expected against current (pre-fix)
      `soar/runner.py` purely by reasoning about the two isolated calls
      above (they don't touch `soar/runner.py`'s own top-level code, so
      they can't "fail before the fix" in the usual red/green sense — the
      fix is a call-site reorder in a module that already ran at import
      time). The real regression check is step below: confirm the two call
      sites in `soar/runner.py` end up in the corrected order.
- [ ] New test: read `soar/runner.py` source and assert the line index of
      `tools.http_client = _build_http_client(config)` is lower than the
      line index of `workflows.init(`. Cheap, direct, and exactly what the
      spec's [S4] success criterion states ("`_build_http_client()`/... вызываются
      раньше `workflows.init()`/...") — avoids the far more complex
      alternative of reloading `soar.runner` as a module in-process (which
      would corrupt the real `soar.tools`/`soar.workflows` singletons used
      by every other test in the session).

## Implementation (`soar/runner.py`)

- [ ] Move `tools.http_client = _build_http_client(config)` and
      `tools.http_client_sync = _build_http_client_sync(tools.http_client)`
      to immediately before `workflows.init(...)` / `connectors.init(...)` /
      `actions.init(...)`.
- [ ] `_build_cache` / `_build_http_client` / `_build_http_client_sync`
      function bodies unchanged — only the call-site position moves.
      `_build_http_client`/`_build_http_client_sync` must be defined
      (as `def`) before they're called in the new position, so the two
      function definitions move up along with their call sites (the
      `_build_cache` helper they depend on moves with them).

## Verification

- [ ] `python -m pytest tests/soar/test_runner.py -v` — all green
- [ ] `python -m pytest tests/ -q` — no new failures vs. baseline (baseline:
      exactly one known pre-existing failure,
      `tests/soar/tools/test_openapi.py::test_generate_config`, unrelated,
      fixed by a separate spec)
- [ ] Check `docs/agents/*.md` for any description of `runner.py`'s init
      call order (spec [S4]/D4); correct if found stale
- [ ] Write report `docs/compose/reports/http-client-init-order.md`
