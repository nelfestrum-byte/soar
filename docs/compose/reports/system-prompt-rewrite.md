---
feature: system-prompt-rewrite
date: 2026-08-05
spec: docs/compose/specs/2026-08-05-system-prompt-rewrite-design.md
plan: docs/compose/plans/2026-08-05-system-prompt-rewrite.md
---

# Report: system prompt rewrite

## What was built

`orchestrator/prompts/system_prompt.md` — the coding agent's built-in
self-description, served verbatim by `GET /prompts/system` — was last
revised 2026-07-29 (v0.15, RBAC boundary + secrets wording). Four releases
later (ENTITY-MODEL Фазы 1-4, 2026-08-03 tools redesign) it had drifted:
wrong storage paths, a completely undocumented way to actually use a
connector from code, a missing endpoint (`GET /runtime`) that answers the
agent's most basic "what can I import" question, and `/tools` examples
naming classes that no longer exist. Docs-only change, no
code/endpoint/schema touched. Restructured from 7 to 8 numbered sections.

Per spec [S2]:

1. **§2 "Entity contracts" — path fix.** Replaced hardcoded
   `soar/connectors/<name>/<name>.py` / `soar/actions/<name>.py` /
   `soar/workflows/<file>.py` with references to the configured
   directories (`connectors_dir`/`actions_dir`/`workflows_dir`, all
   `/app/data/...` by default, `orchestrator/config.py:50-52`) and an
   explicit statement that content lives outside `soar/` on disk — `soar/`
   ships contract and base classes only. Kept everything else in the
   section unchanged (registry-key-by-filename, `_ensure_connected`, Tool
   read-only).
2. **New §3 "Using a connector from your code."** Neither this nor any
   prior revision of the file documented how workflow/action code actually
   obtains a connector instance. Added both forms
   (`orchestrator/api/workflows.py:24-32`) with a short example, and the
   two concrete reasons the concept form (`from soar.connectors.<type>
   import <instance>`) is preferred over the flat form: import-time
   failure instead of a mid-job `AttributeError`, and — the more
   consequential one — it's what credential scoping reads to decide which
   connector instances' config a job's subprocess receives
   (`docs/concepts/ENTITY-MODEL.md` E6/Решение 4, "сужение кредов до
   задачи").
3. **New §7 bullet (conventions)** — cross-references §3: static,
   module-level imports are what credential scoping sees; an instance only
   reached via the flat form or dynamic/conditional logic may fall outside
   the scope a job receives.
4. **§6 "Self-description" (was §5) — `/tools` examples replaced.** The
   old text's generic `HttpClient`/`OpenAPIGenerator` examples don't exist
   post-redesign (`docs/compose/reports/tools-redesign.md`). Replaced with
   the current `TOOL_REGISTRY` contents (`soar/tools/__init__.py:21-30`):
   `http_client`, `LoggingHttpClient`/`CachingHttpClient`, `new_client()`,
   `WatermarkStore`/`SeenStore` + factories.
5. **New `GET /runtime` bullet in §6.** Implemented
   (`orchestrator/api/runtime.py`) as part of ENTITY-MODEL Фаза 3 but never
   surfaced in the prompt — it's the direct, load-bearing answer to "what
   can I import beyond `soar/tools/`," distinguishing `guaranteed`
   (runtime-contract packages) from `present_not_guaranteed` (installed but
   not promised).
6. **§5 "Dev loop" (was §4) — one clause added.** The validate-before-write
   bullet now states explicitly that `ast.parse` checks syntax/entry-point
   only, not import resolution — closing a gap where an agent might assume
   a successful `PUT` means the code will actually run.
7. **New §8 bullet (known risks)** — mirrors the §5 addition from the
   risk side: an unresolved connector-instance import or an out-of-contract
   package isn't caught at write time, only as a job traceback (§6/§5
   cross-referenced both ways).
8. **§4 "Your access" (was §3) — one addition.** Added
   `POST /connectors/pack/install` to the excluded-endpoints list
   (`orchestrator/api/packs.py:23`, admin-only, same risk category as
   `/transfer/import` per the file's own docstring) — new since v0.15, not
   previously excludable because it didn't exist.

All other content (RBAC role boundary and the B3 `PUT /connectors/{name}/code`
exception in §4, dev-loop traceback/history/diff/restore in §5, dry-run/
lazy-connect/webhook-token in §7, secrets write-only/P10 in §8) was
re-verified against current source (table below) and carried over
unchanged in substance, only renumbered.

## Facts verified before writing (spec [S3])

Read current source directly, not carried over from the prior revision:
`orchestrator/config.py:49-55` (directory defaults),
`orchestrator/api/workflows.py:24-76` (both import forms in all three
templates), `docs/concepts/ENTITY-MODEL.md:248-280,454-459,497-506` (why
the concept form matters), `orchestrator/api/runtime.py` (full
`GET /runtime` implementation), `soar/tools/__init__.py:1-32`
(`TOOL_REGISTRY`, 8 entries), `orchestrator/api/tools.py` (how the
registry is resolved), `docs/compose/reports/tools-redesign.md` (redesign
shipped as described). Additionally re-verified the v0.15 RBAC table
against current `_RO`/`_RW`/`_ADMIN` tuples in `connectors.py`,
`actions.py`, `workflows.py`, plus the literal-`admin` gates in
`connectors.py:523` (B3), `transfer.py`, `audit.py`, `packs.py:23`,
`auth/router.py` — all unchanged since v0.15 except the new
`/connectors/pack/install` route, which didn't exist at that revision.

## Verification

- `python -m pytest tests/orchestrator/api/test_prompts_api.py -q`: **5
  passed** — endpoint behavior unaffected (tests check status
  code/response shape via a temp-file fixture, not this file's content).
- Read the full file back after editing and grepped every `§n`
  cross-reference (`grep -n "§\d"`) to confirm each pointer resolves to
  the section it names under the new 1-8 numbering — caught and fixed
  five stale references left over from drafting against a mistaken
  9-section count (§7→§6, §5→§4, §8→§7, §9→§8 ×3) before finalizing.
- Cross-checked RBAC facts in §4 against live route definitions (see
  above) rather than trusting the prior revision's table.

## Deviations from the plan

- Ended up with 8 numbered sections, not 9 — the spec's section list in
  [S2] miscounted the unnumbered header as its own item. No content is
  missing; the checklist mapping (old §N → new §N) in the plan still holds
  correctly for the 8 sections actually produced.
