---
feature: runtime-boundary
date: 2026-07-30
spec: docs/compose/specs/2026-07-30-runtime-boundary-design.md
plan: docs/compose/plans/2026-07-30-runtime-boundary.md
---

# Report: Runtime Boundary — Phase 1 модели сущностей

Branch: `feat/runtime-boundary-phase1` (off `main` @ `d3e467b`, which already
contained `docs/concepts/ENTITY-MODEL.md` and the full spec/plan set for all
four phases).

## What was built

All five parts of the phase, in the dependency order the spec requires
(content venv → dependency contract → `GET /runtime`; AST workflow metadata
and the audit hook as the two independent-but-bundled pieces):

1. **`soar/runtime_contract.py`** — `RUNTIME_VERSION = "1"` and `CONTRACT`
   (dist name → `import_names`/`kind`), exactly as specced. Versions are not
   duplicated — `soar/requirements.txt` stays the only source, verified by a
   two-way test (`CONTRACT` keys ⊆ requirements lines, and vice versa).

2. **Content venv** — `orchestrator/core/subprocess_runner.py` gained
   `resolve_content_python()` (reads `SOAR_CONTENT_PYTHON`, falls back to
   `sys.executable`) and a module-level `_CONTENT_PYTHON` used by
   `SubprocessRunner.start()` instead of the bare `sys.executable`.
   `orchestrator/main.py::lifespan` sets `app.state.content_python =
   resolve_content_python()` (same resolver, one source of truth for both
   the subprocess launcher and `GET /runtime`).
   `deploy/{prod,stage}/Dockerfile.orchestrator` now build two venvs:
   `/app/platform-venv` (from `orchestrator/requirements.txt`, put on
   `PATH`) and `/app/content-venv` (from `soar/requirements.txt`, **not** on
   `PATH`), with `SOAR_CONTENT_PYTHON=/app/content-venv/bin/python`. This is
   the change that actually closes **E2** — `soar/requirements.txt` was
   installed nowhere before this; the old Dockerfiles hand-listed
   `elasticsearch vt-py requests httpx` and left 11 of 24 built-in
   connectors' dependencies missing.

3. **AST workflow metadata** — `orchestrator/core/introspect.py` gained
   `parse_workflow_meta()`, reusing the existing `_target_name` helper
   (unchanged). `orchestrator/main.py::load_workflow_metas` no longer does
   `from soar.workflows import workflows as wf_registry; wf_registry.init()`
   — it now scans `_SOAR_PKG / "workflows"` then `config.soar.workflows_dir`
   (same priority order as the old `WorkflowRegistry._discover()` /
   `_discover_external()`, deduped by filename stem) and parses each file's
   AST directly. The orchestrator process no longer imports user workflow
   code on any reload (closes **E10.3**). `WorkflowMeta` shape, the four
   call sites in `orchestrator/api/workflows.py`, and `job_manager.set_metas`
   / `scheduler.reload` behavior are unchanged.

4. **Audit hook** — new `soar/audit_hook.py`
   (`sys.addaudithook`-based: watches `socket.connect`, `socket.getaddrinfo`,
   `open`, `subprocess.Popen`, `exec`, `ctypes.dlopen`; blocks
   `socket.connect` to private/loopback/link-local/multicast/reserved
   addresses with `PermissionError`; batches everything else into `_events`,
   flushed via `flush()`). Installed in `soar/runner.py` right after
   `setup_logging()`, before `config_path = ...` / `tools.http_client = ...`
   / any `*.init()` call. The existing SSRF pre-flight check in
   `soar/tools/http_client.py::_validate_external_url` is untouched, per the
   spec's rationale (pre-flight gives a clean `ValueError` before opening a
   socket; the hook is the backstop for everything that isn't HTTP —
   paramiko, ldap3, pymssql, raw sockets).

5. **`GET /runtime`** — new `orchestrator/api/runtime.py`, read-only
   (`_RO` roles, no PUT/DELETE, same category as `/tools`), registered in
   `orchestrator/api/__init__.py` and `orchestrator/main.py` next to
   `tools_router`. Introspects `app.state.content_python`'s venv via
   `importlib.metadata.distributions(path=...)`, splits installed packages
   into `guaranteed` (declared in `CONTRACT` and actually installed —
   `distribution`/`version`/`import_names`/`kind`) and
   `present_not_guaranteed` (installed but undeclared, `import_names`
   derived from `top_level.txt`). Closes **E9**.

6. **Docs** — `docs/agents/known-limitations.md` #10 (E2) marked closed with
   a pointer to this report. `AGENTS.md`: quick known-limitations list #10/#11
   marked closed, File map gained `orchestrator/api/runtime.py`,
   `soar/runtime_contract.py`, `soar/audit_hook.py`, API-endpoints quick
   reference gained `/runtime`. `docs/agents/api-reference.md` gained a
   `### Runtime` section.

## Deliberate deviations from the literal spec/plan

The spec explicitly left some things for implementation time; a few others
turned out to need a call I made and am flagging here:

1. **`smbprotocol` import names** — confirmed against the actually-installed
   package in this dev environment: `importlib.metadata.distribution
   ('smbprotocol').read_text('top_level.txt')` returns both `smbclient` and
   `smbprotocol`. Matches the spec's `CONTRACT` entry as-written; no change
   needed, just verified rather than assumed.

2. **Webhook token generation when the AST can't extract a literal
   constant** — the biggest real judgment call in this phase.
   `orchestrator/api/workflows.py::WEBHOOK_TEMPLATE` (existing, unrelated
   file, not touched) scaffolds new webhook workflows with
   `token = secrets.token_urlsafe(32)` as a **class-level call expression**,
   not a literal. The old import-based path evaluated this at import time,
   producing a real random token on first import, which `load_workflow_metas`
   then persisted to `orchestrator_state.yaml` and reused on every later
   call. AST parsing only extracts `ast.Constant` values (per spec), so a
   call expression yields no `token` at all — `meta.get("token")` is `None`.
   Applied literally, this would silently and permanently null out every
   webhook token that isn't a hardcoded string literal, past or future,
   including the one produced by the platform's own creation template —
   `orchestrator/api/webhooks.py`'s `secrets.compare_digest(token,
   meta.token)` check would then reject every request, since `meta.token`
   would stay falsy forever. Existing regression test
   `test_load_workflow_metas_persists_webhook_token_across_calls` (already
   in the repo, unrelated to this phase) exercises exactly this path and
   would fail.

   Fix: `load_workflow_metas` now falls back to `secrets.token_urlsafe(32)`
   when a webhook workflow has neither a saved token in state nor an
   AST-extractable literal one — `token = parse_token(saved) or token or
   secrets.token_urlsafe(32)` — generating and persisting a token the first
   time such a workflow is seen, exactly matching what the old import-based
   path did on first import. No changes to `orchestrator/api/workflows.py`
   or its template were needed or made; this is confined to
   `orchestrator/main.py`.

3. **Audit hook install gated on `if __name__ == "__main__":`** — the spec's
   `soar/runner.py` snippet calls `install_audit_hook()` unconditionally at
   module level. `sys.addaudithook` has no `removeaudithook` — once
   installed, it's active for the rest of that process, forever.
   `tests/soar/test_runner.py` (existing, unrelated file) does
   `from soar import runner` directly in-process to unit-test `runner.main()`
   and `runner._build_http_client` without spinning a real subprocess; this
   import happens during pytest **collection**, before any test runs. With
   the spec's literal unconditional call, the very first full-suite run
   installed the hook once and it stayed active for the rest of the pytest
   process — 397 tests downstream started failing with `PermissionError`
   the moment any of them touched a real loopback socket (Redis queue
   tests, scheduler/worker tests, `soar/tools/test_http_client.py`'s mocked
   `socket.getaddrinfo` tests, etc. — all legitimately use `127.0.0.1` in
   their fixtures). Verified this is a real, deterministic effect (not
   flakiness) by running the full suite before and after the fix.

   Fix: the install call is gated on `if __name__ == "__main__":`, placed
   at the same point in the file (right after `setup_logging()`, before the
   config/http_client/`*.init()` block). `python -m soar.runner` — the only
   way this module is ever invoked in production (via `SubprocessRunner`) —
   always runs as `__main__`, so the hook still installs before any content
   code runs, exactly per the spec's ordering requirement. Plain `import
   soar.runner` (test-only, in-process) no longer installs it. This is
   noted inline in `soar/runner.py` with the reasoning.

4. **Two small mypy type-narrowing additions in `parse_workflow_meta`** —
   not in the spec's snippet, added to keep the pre-existing mypy baseline
   at zero new findings: an explicit `isinstance(item, (ast.AnnAssign,
   ast.Assign))` check before accessing `item.value` (the spec's loop body
   accessed `.value` on a bare `ast.stmt`, which doesn't have that attribute
   statically), and `meta: dict[str, object]` instead of a bare `meta = {...}`
   (mypy otherwise infers `dict[str, str]` from the first two literal keys
   and rejects the later `meta[name] = item.value.value` assignment, which
   can be `int`/`bool`/etc.). No behavior change — verified against all
   `parse_workflow_meta`/`load_workflow_metas` tests.

5. **`httpx` added to `orchestrator/requirements.txt`** — found only by
   actually building and starting the image (unit tests can't catch this;
   they run against the single dev venv where everything is already
   installed). `orchestrator/api/connectors.py` does a real top-level
   `from soar.tools.openapi import OpenAPIGenerator` (used for
   OpenAPI-spec→connector generation, an existing, pre-Phase-1 feature).
   Importing any `soar.tools.*` submodule runs `soar/tools/__init__.py`
   first, which unconditionally does `from soar.tools.http_client import
   HttpClient, SyncHttpClient` and instantiates both — pulling `httpx` in as
   a real, load-bearing platform dependency, even though
   `soar/tools/openapi.py` itself is pure stdlib. Before this phase this
   worked by accident (platform and content shared one venv with `httpx`
   hand-listed in the old single-`pip install` Dockerfile line). After the
   split, the orchestrator container failed at startup with
   `ModuleNotFoundError: No module named 'httpx'` the moment
   `orchestrator/main.py` imported `orchestrator.api` — this is a hard
   startup crash, not a degraded-mode warning. I grepped the rest of
   `orchestrator/` for other `from soar.` top-level imports first (only
   other hits are inside template *string literals* in
   `orchestrator/api/workflows.py`/`connectors.py` — scaffold source text
   for generated files, never executed by the orchestrator process itself)
   to confirm this was the only real gap, then added `httpx>=0.27.0`
   (same constraint as `soar/requirements.txt`) to
   `orchestrator/requirements.txt` with an inline comment explaining why.
   The proper fix — orchestrator not importing content-designated code at
   all — is Phase 2/3 territory (`docs/concepts/ENTITY-MODEL.md`, "content
   as a contentpack"); out of scope here.

6. **`_content_venv_root` uses `.absolute()`, not `.resolve()`** — the
   spec's `orchestrator/api/runtime.py` snippet does
   `Path(content_python).resolve().parent.parent`. This is wrong on POSIX:
   `python -m venv` creates `bin/python` as a symlink to the *base*
   interpreter (confirmed in the built image:
   `/app/content-venv/bin/python -> python3.11 -> /usr/local/bin/python3.11`).
   `.resolve()` follows symlinks, so it chased straight past the venv into
   the base image's own install, and `GET /runtime` silently reported the
   base image's site-packages (`pip`/`setuptools`/`wheel`/`packaging` only)
   as `present_not_guaranteed`, with an empty `guaranteed` list and
   `python_version: null` — the endpoint returned 200 with a plausible-looking
   but completely wrong answer, the worst kind of bug for something whose
   whole purpose is being a trustworthy contract. Unit tests didn't catch
   this either (they mock `_site_packages` directly, matching the plan's own
   test guidance — reasonable for a unit test, but it means this class of
   bug is only visible against a real venv). Caught during the manual Docker
   verification pass, confirmed the symlink chain with `readlink -f` inside
   the container, fixed by switching to `.absolute()` (keeps the literal
   `SOAR_CONTENT_PYTHON`/`sys.executable` path without following symlinks),
   rebuilt, and re-verified end-to-end with a real admin JWT against the
   running container — all 17 `CONTRACT` packages now come back correctly
   in `guaranteed` with real installed versions, and `python_version` reads
   `"3.11.15"`. See inline comment in `orchestrator/api/runtime.py` for the
   full explanation.

## Verification

- **`python -m pytest tests/ -q`**: **811 passed, 1 skipped, 0 failed**
  (baseline before this phase: 780 passed, 1 skipped, 0 failed — the +31 are
  new tests added by this phase: 5 for `runtime_contract`, 4 for
  `resolve_content_python`/`SubprocessRunner.start`, 9 for
  `parse_workflow_meta`, 3 for `load_workflow_metas` regression/non-import
  coverage, 9 for `audit_hook`, 4 for `GET /runtime` — some existing files
  also gained assertions counted individually). Zero new failures, zero
  regressions in unrelated suites (redis queue, scheduler, worker, http
  client, webhook auth, RBAC). Side note, not a regression:
  `tests/orchestrator/test_redis_integration.py` needs a real Redis
  reachable at `localhost:6379` to *pass*; its fixture's `except Exception:
  pytest.skip(...)` only guards the initial `clear()` call, not the test
  body, so when Redis is unreachable it fails with a raw `ConnectionError`
  instead of skipping. Confirmed via `git stash` that this reproduces
  identically with zero code changes — pre-existing test fragility,
  unrelated to this phase, incidentally surfaced because the Docker
  verification below started and later tore down a real Redis container on
  that same port.
- **`ruff check .`**: 43 findings, all pre-existing (verified via `git
  stash`/re-run — baseline was 45; my new files contribute zero, and net
  count actually dropped by 2 for reasons unrelated to this phase's new
  code). One new finding (`B007` unused loop variable in my own new test
  file) was caught and fixed before the final count.
- **`mypy orchestrator/ soar/ --ignore-missing-imports`**: 120 findings,
  identical to the pre-existing baseline (verified via `git stash`). Two
  findings introduced by `parse_workflow_meta`'s spec-literal code were
  fixed (see deviation #4 above) rather than left as new baseline noise,
  since fixing them was cheap and didn't touch behavior.
- **Docker build/run verification** — Docker Desktop was available in this
  environment; ran the full manual-verification checklist from the plan
  against `deploy/stage`, not skipped:
  - `docker compose -f deploy/stage/docker-compose.yml build orchestrator` —
    succeeds, both venvs build (platform-venv from
    `orchestrator/requirements.txt`, content-venv from
    `soar/requirements.txt`).
  - `docker compose ... run --rm orchestrator /app/content-venv/bin/python -c
    "import paramiko, ldap3, psycopg2, pymysql, pymssql, aiogram, shodan,
    pymisp, elasticsearch, vt, winrm, smbprotocol, httpx, requests, yaml,
    loguru"` — succeeds, no `ImportError` (closes **E2** for real, not just
    on paper).
  - `docker compose ... run --rm orchestrator python -c "import fastapi,
    sqlalchemy, alembic"` (bare `python`, resolves via `PATH` to
    platform-venv) — succeeds.
  - `docker compose ... run --rm orchestrator /app/content-venv/bin/python -c
    "import fastapi"` — fails with `ModuleNotFoundError`, as required: the
    boundary is physically real, not just a documentation claim.
  - Full container smoke test (`docker compose up -d orchestrator`, real
    Postgres+Redis dependencies): starts clean, `GET /health` → `200
    {"status":"ok"}`. Created a real admin user via
    `orchestrator.auth.cli create-user`, logged in, called `GET /runtime`
    with a real JWT: `runtime_version: "1"`, `python_version: "3.11.15"`,
    all 17 `CONTRACT` packages present in `guaranteed` with real installed
    versions (`paramiko 5.0.0`, `smbprotocol 1.17.0` with both
    `smbclient`/`smbprotocol` import names, `httpx 0.28.1`, etc.), and a
    correctly-populated `present_not_guaranteed` list of transitive
    dependencies (aiohttp, cryptography, urllib3, ...).
  - This pass caught two real defects invisible to unit tests (deviations
    5 and 6 above: missing `httpx` in `orchestrator/requirements.txt`, and
    `_content_venv_root`'s `.resolve()` following the venv's symlink out to
    the base interpreter) — both fixed, image rebuilt, re-verified
    end-to-end after each fix.
  - Torn down (`docker compose down`) after verification; nothing left
    running.

## Files touched

- `soar/runtime_contract.py` (new), `soar/audit_hook.py` (new)
- `soar/runner.py` — audit hook install (gated), `finally: flush_audit_hook()`
- `orchestrator/core/subprocess_runner.py` — `resolve_content_python()`
- `orchestrator/core/introspect.py` — `parse_workflow_meta()` + helpers
- `orchestrator/main.py` — `load_workflow_metas` rewritten, `_iter_workflow_files`,
  `app.state.content_python`, `runtime_router` registration
- `orchestrator/api/runtime.py` (new), `orchestrator/api/__init__.py`
- `deploy/prod/Dockerfile.orchestrator`, `deploy/stage/Dockerfile.orchestrator`
- `orchestrator/requirements.txt` — added `httpx` (deviation 5, found via Docker verification)
- `docs/agents/known-limitations.md`, `AGENTS.md`, `docs/agents/api-reference.md`
- Tests: `tests/soar/test_runtime_contract.py` (new),
  `tests/soar/test_audit_hook.py` (new),
  `tests/orchestrator/api/test_runtime.py` (new),
  `tests/orchestrator/test_subprocess_runner_env.py`,
  `tests/orchestrator/core/test_introspect.py`,
  `tests/orchestrator/test_load_workflow_metas.py`

## Not done in this phase

Phases 2–4 of the entity model (entity model in code, content as a
contentpack, privilege narrowing) — specced and planned already
(`docs/compose/specs/2026-07-30-*`, `docs/compose/plans/2026-07-30-*`) but
explicitly out of scope here per "весь план целиком, потом релиз": this
report covers Phase 1 only, not merged to `main`.
