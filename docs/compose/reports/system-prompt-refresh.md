---
feature: system-prompt-refresh
date: 2026-07-29
spec: docs/compose/specs/2026-07-29-system-prompt-refresh-design.md
plan: docs/compose/plans/2026-07-29-system-prompt-refresh.md
---

# Report: system prompt refresh

## What was built

`orchestrator/prompts/system_prompt.md` — the coding agent's built-in
self-description, served verbatim by `GET /prompts/system` — was last
written for Agent Dev-Loop Этап 2 (2026-07-22) and never revisited, even
though Этап 3 (`agent` RBAC role) and the v0.14 bugfix pass (B3) both
changed facts it states about the agent's own access. Docs-only change,
no code/endpoint/schema touched.

Three edits, per spec [S2]:

1. **New §3 "Your access (role `agent`)"**, inserted between the entity
   contracts section and the dev-loop section (all following sections
   renumbered +1, §3→§7 final). States the role boundary in one line
   ("code and jobs, not administration"), lists the four excluded
   endpoint groups (`/auth/*`, `GET /audit-log`, `/transfer/*`,
   `PUT /prompts/user`), and calls out the B3 exception —
   `PUT /connectors/{name}/code` needs literal `admin` even though
   `agent` can write workflow code, action code, and connector config
   freely — with the reason (connector code is where `HIDDEN_FIELDS` is
   declared; letting `agent` rewrite it would let it strip its own
   redaction).
2. **§2 fix** — the line asserting `PUT .../code`/`DELETE` are uniformly
   "(admin)" across all three entity types was accurate before Этап 3 but
   is now wrong for workflow/action code (both open to `agent`) and only
   right by coincidence for connector code. Replaced with a pointer to
   §3 instead of a blanket claim.
3. **§7 (was §6) "Known risks" — rewrote the P6 item.** It previously
   said `GET /connectors/{name}/config` "returns the YAML as-is,
   including passwords/tokens/API keys" — true when written, false since
   v0.12 (`docs/compose/reports/connector-secrets-schema.md`): every
   `HIDDEN_FIELDS` value is now redacted to `"********"` for all roles
   including `admin`. Replaced with the actual behavior and its two
   practical consequences for the agent: don't treat `"********"` as a
   real value, and `PUT /config` is merge-on-write so only send a real
   value for a field actually being changed. Also added that changing a
   hidden field to a real value needs literal `admin` (`agent` gets `403`
   on that field specifically, non-hidden fields in the same request
   still go through).
4. **Small addition to §5 (self-description)** — a bullet for
   `GET /connectors/{name}/schema` (typed fields + `hidden: bool`),
   directly useful alongside the rewritten §7 so the agent can check
   which fields will come back masked before attempting a config write.
   Not in the original plan's explicit scope but a one-line, same-style
   addition that makes the risk note in §7 actionable rather than just a
   warning.

## Addendum [S3a] — Tool as a fourth, read-only entity

Follow-up during implementation: §2 ("entity contracts") only named the
three API-writable entities, even though §5 already told the agent to
call `GET /tools` — introducing a concept before naming it. Renamed §2
from "The three entity contracts" to "Entity contracts", added `Tool`
(`soar/tools/`) as a fourth bullet explicitly marked read-only — no
`PUT`/`DELETE` exists for it under any role, per `AGENTS.md`'s
"движок vs поведение" principle (`tools/` is generic infrastructure
changed only by code release, not API). Narrowed the following
"read/written through symmetric API groups" paragraph to name only
Action/Connector/Workflow, since it no longer applies to all four
bullets above it. Re-ran `tests/orchestrator/api/test_prompts_api.py`
after this change too — still 5 passed (content-agnostic, as expected).

## Facts verified before writing (spec [S3])

Read current source directly, not carried over from stale docs:
`orchestrator/api/{actions,connectors,workflows,jobs,logs,tools,status,
prompts,audit,transfer}.py` and `orchestrator/auth/router.py` — confirmed
the exact `_RO`/`_RW`/`_ADMIN`/`_ANALYST` tuple membership per file, and
that `connectors.py:519` (`PUT /{name}/code`) is the only write route
gated on the literal `"admin"` string outside the six already-documented
admin-literal routes (`/auth/*`, `/audit-log`, `/transfer/*`). Also
re-read `docs/agents/security-patterns.md`'s "Connector secret redaction"
section to confirm the `"********"`/merge-on-write/literal-admin-gate
description used in the new §7 text matches the implemented behavior, not
just the spec that proposed it.

## Verification

- `python -m pytest tests/orchestrator/api/test_prompts_api.py -q`: **5
  passed** — endpoint behavior is unaffected (tests check status
  code/response shape via a temp file fixture, not this file's content),
  confirming no code path needed to change for the new content to take
  effect through `GET /prompts/system`.
- Read the full file back after editing to confirm section numbering is
  sequential (1-7, no gaps/dupes) and the new §3 doesn't restate §7's
  content or vice versa — cross-referenced with "see §3"/"see §7" instead
  of duplicating.

## Deviations from the plan

- Added the `GET /connectors/{name}/schema` bullet to §5 (self-description
  section), which the spec didn't explicitly call for — included because
  it makes the new §7 risk note actionable (agent can check `hidden` per
  field before writing) rather than descriptive, and follows the existing
  bullet style exactly (one line, cross-references the relevant risk
  section). No other deviation — §2/§3/§7 changes match the spec's [S2]
  exactly.
