# System prompt rewrite — bring `orchestrator/prompts/system_prompt.md` in line with current API

> Docs-only change: no application code, no new endpoint. This is the
> second revision of the file since it shipped in Agent Dev-Loop Этап 2
> (`docs/compose/specs/2026-07-22-agent-devloop-stage2-design.md`) — the
> first was `2026-07-29-system-prompt-refresh-design.md` (v0.15, RBAC
> boundary + secrets wording). This one covers everything that changed
> since: ENTITY-MODEL Фазы 1-4 (content-pack separation, lazy import
> shims, `GET /runtime`) and the 2026-08-03 tools redesign.

## [S1] Problem

`orchestrator/prompts/system_prompt.md` is the coding agent's only
self-description, served verbatim by `GET /prompts/system` and read "before
touching anything else" (file's own line 3-5). It was last revised
2026-07-29 (v0.15). Four releases later it is stale or incomplete in ways
that cost the agent turns, not just cosmetically wrong:

1. **§2 states literal in-package paths that are no longer where content
   lives.** `soar/connectors/<name>/<name>.py`, `soar/actions/<name>.py`,
   `soar/workflows/<file>.py` describe the pre-content-pack layout. Storage
   is now the configured directories (`orchestrator/config.py:50-52`):
   `connectors_dir="/app/data/connectors"`, `actions_dir="/app/data/actions"`,
   `workflows_dir="/app/data/workflows"` — outside the `soar/` package,
   following ENTITY-MODEL Фаза 3 (content pack separation, confirmed by the
   stale-import bug found during the 2026-08-03 tools redesign: 24
   `soar-content-pack/connectors/*/__init__.py` files still had
   `soar.connectors.<name>.<name>` imports left over from this exact
   rename, `docs/compose/reports/tools-redesign.md` "Побочная находка").
2. **The prompt never says how to use a connector from workflow/action
   code.** Two forms exist, both proxied
   (`orchestrator/api/workflows.py:24-32`): the concept form
   `from soar.connectors.<type> import <instance>` and the flat form
   `from soar.connectors import connectors` + `connectors.<instance>`. The
   concept form is preferred for a concrete, non-cosmetic reason: it is
   statically analyzable, so (a) the orchestrator derives the job's
   credential scope from it — only the connector instances a workflow
   actually imports get their config handed to the subprocess
   (ENTITY-MODEL E6/Решение 4, "сужение кредов до задачи") — and (b) a
   typo in the instance name fails at import time (`ImportError`, caught by
   `validate_workflow_code`/IDE) instead of `AttributeError` inside an
   already-running job. An agent that only knows the flat form gets neither
   property and has no way to learn this from the current document at all.
3. **`GET /runtime` (`orchestrator/api/runtime.py`) is unmentioned.**
   Implemented as part of ENTITY-MODEL Фаза 3 (E9/E10 — "environment
   explains itself through the API," AGENTS.md principle 4): returns
   `guaranteed` (packages in `soar/runtime_contract.py::CONTRACT`, safe to
   import) vs `present_not_guaranteed` (installed in the content venv but
   not part of the contract — may disappear on the next build) for the
   *content* venv specifically, not the platform's. This is the direct
   answer to "what can I import," which §5 (self-description) otherwise
   leaves the agent unable to answer without guessing or crashing a job.
4. **§5's `/tools` examples are gone from the codebase.** The 2026-08-03
   tools redesign (`docs/compose/specs/2026-08-03-tools-redesign-design.md`)
   deleted the async `HttpClient` the prompt doesn't even mention by name
   but implicitly assumed (via generic "e.g. `HttpClient`"), replacing it
   with `LoggingHttpClient`/`CachingHttpClient` (sync `httpx.Client`
   subclasses) and `new_client()`, all listed in the new
   `soar/tools/__init__.py::TOOL_REGISTRY` (`soar/tools/__init__.py:21-30`)
   — the literal source `GET /tools` now reads via AST
   (`orchestrator/core/introspect.py::parse_tool_registry`).

Everything else — the `agent` RBAC boundary (§3), dev loop (§4:
validate-before-write, traceback, history/diff/restore), conventions (§6:
dry-run, lazy connect, stable webhook token), and the secrets/P10 risk
items (§7) — was verified against current source during this task and
remains accurate; renumbered but not rewritten in substance.

## [S2] Solution overview

Edit `orchestrator/prompts/system_prompt.md` only, restructuring from 7 to
9 sections:

1. Header — unchanged.
2. What SOAR is — unchanged.
3. Entity contracts — rewrite the path bullets to reference the
   configured directories instead of hardcoded `soar/...` paths; keep
   everything else (registry-key-by-filename for Action/Workflow,
   `BaseConnector`/`_ensure_connected` for Connector, Tool read-only).
4. **New section: "Using a connector from your code"** — both import
   forms, the credential-scoping and fail-fast reasons the concept form is
   preferred, one code example of each.
5. Your access (role `agent`) — carried over from v0.15, re-verified, no
   content change expected.
6. Dev loop — carried over, add one clause to the validate-before-write
   bullet: `ast.parse` checks syntax/entry-point only, not whether
   imported names resolve (cross-reference to the new §9 risk item this
   creates).
7. Self-description — update `/tools` bullet to name
   `LoggingHttpClient`/`CachingHttpClient`/`new_client`/`WatermarkStore`/
   `SeenStore` instead of the now-nonexistent generic `HttpClient`
   example; add a new bullet for `GET /runtime`
   (guaranteed vs present-not-guaranteed content-venv packages).
8. Conventions worth knowing — carried over, add one bullet: static,
   module-level connector imports are what the credential-scoping
   mechanism (§4) sees; an instance resolved only through the flat
   `connectors.<name>` form or behind conditional/dynamic logic may not be
   in the credential set the job subprocess receives.
9. Known risks — carried over (secrets write-only, P10 concurrency), add
   one item: `PUT .../code` validates syntax and entry-point only; an
   import of a nonexistent connector instance or a package outside the
   runtime contract (§7) is not caught here — it surfaces as a traceback
   in `GET /jobs/{id}` (§6) the first time the workflow actually runs.

## [S3] Facts verified against current source (not re-derived from memory)

Read directly from the files below on 2026-08-05, current `main`:

| File | What it establishes |
|---|---|
| `orchestrator/config.py:49-55` | `SoarConfig` — `connectors_dir`/`actions_dir`/`workflows_dir` all default to `/app/data/...`, outside `soar/`; `tools_dir="soar/tools"` (platform code, stays in-package by design); `system_prompt_path` |
| `orchestrator/api/workflows.py:24-76` | All three workflow templates (scheduled/webhook/manual) show both import forms in comments/code; docstring at line 24-29 names the source (`docs/concepts/ENTITY-MODEL.md` decision 4) and confirms both forms return a `ConnectorProxy` |
| `docs/concepts/ENTITY-MODEL.md:248-280` (E6), `:454-459` (credential scoping), `:497-506` (Решение 4) | Why the concept form exists: import-time resolution catches typos before rather than during a job; static import list drives which connector instances' credentials the subprocess receives |
| `orchestrator/api/runtime.py` | `GET /runtime` — full implementation; introspects the *content* venv (`request.app.state.content_python`), returns `runtime_version`, `python_version`, `guaranteed` (from `CONTRACT`), `present_not_guaranteed` |
| `soar/tools/__init__.py:1-32` | Current `TOOL_REGISTRY`: `http_client` (instance of `LoggingHttpClient`), `LoggingHttpClient`, `CachingHttpClient`, `new_client` (factory), `WatermarkStore`, `SeenStore`, `watermark_store`, `seen_store` (factories) — 8 entries, no `HttpClient`/`SyncHttpClient`/`OpenAPIGenerator` (all three gone or never existed under those names) |
| `orchestrator/api/tools.py` | `GET /tools`/`GET /tools/{name}` read `TOOL_REGISTRY` via `parse_tool_registry` (AST, never imports `soar/tools/`); unresolved entries return `{"error": "unresolved"}` rather than a synthetic stub |
| `docs/compose/reports/tools-redesign.md` | Confirms the redesign shipped as described, migration to sync `httpx.Client`-based tools complete, `GET /tools` returns exactly 8 entries |
| `tests/orchestrator/api/test_prompts_api.py` | No test asserts `system_prompt.md`'s literal content — only that the endpoint reads/writes whatever file is configured; content rewrite carries zero test risk |

## [S4] Non-goals

- Not touching `orchestrator/prompts/user_prompt.md` (operator-supplied,
  out of scope, same as the prior revision).
- Not adding a one-shot example library — still deferred per `UPGRADE.md`
  Часть 3 (P4-примеры).
- Not changing any RBAC code, endpoint, template, or test — this spec only
  corrects and extends what the prompt *says* about behavior that already
  exists (content-pack paths, import forms, `/runtime`, tools redesign are
  all already shipped and tested).
- Not documenting `POST /connectors/pack/install` (bulk content-pack
  install) — admin-only, external-code-entering-instance risk category
  same as `/transfer/import`; the `agent` role cannot call it, so it's not
  part of the agent's own operating surface, same reasoning the existing
  prompt already applies to `/transfer/*`.
- Not documenting Слой 3 process isolation (UID/rlimit narrowing,
  ENTITY-MODEL Фаза 4) — deployment-level hardening invisible to the
  agent's HTTP-only view of the system; nothing at the API surface changes
  because of it.

## [S5] Success criteria

- [ ] §3 (entity contracts) states connector/action/workflow storage via
      the configured directories, not hardcoded `soar/...` paths.
- [ ] New §4 documents both connector-import forms, states which is
      preferred and why (credential scoping + import-time failure), with
      one short code example.
- [ ] §7 (self-description) names the current `TOOL_REGISTRY` contents
      instead of the removed `HttpClient`, and includes a `GET /runtime`
      bullet.
- [ ] §8/§9 (conventions/risks) each gain the one cross-referenced bullet
      described in [S2] — static imports and credential scoping;
      syntax-only validation and where unresolved-import failures surface.
- [ ] Full read-through: section numbers 1-9, sequential, no section
      restates another's content without a cross-reference.
- [ ] `python -m pytest tests/orchestrator/api/test_prompts_api.py -q`
      still passes (content-agnostic, expected to be unaffected).
