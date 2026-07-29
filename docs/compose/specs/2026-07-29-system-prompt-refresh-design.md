# System prompt refresh — bring `orchestrator/prompts/system_prompt.md` in line with v0.14

> Docs-only change: no application code, no new endpoint. Existing pattern for
> touching this file — it shipped as part of Agent Dev-Loop Этап 2
> (`docs/compose/specs/2026-07-22-agent-devloop-stage2-design.md`) and has not
> been revisited since, even though Этап 3 and the v0.14 bugfix pass both
> changed the facts it states about the agent's own access.

## [S1] Problem

`orchestrator/prompts/system_prompt.md` is served verbatim by `GET
/prompts/system` — it is the coding agent's only self-description of what it
is and what it may do, read once "before touching anything else" (per the
file's own line 3-5). It was written during Agent Dev-Loop Этап 2
(2026-07-22) and never updated. Two releases later (Этап 3 / v0.14) it is
stale in ways that actively mislead the agent, not just incomplete:

1. **§6 "P6 — connector secrets are returned in plaintext" is now false.**
   Since v0.12 (`docs/compose/reports/connector-secrets-schema.md`),
   `GET /connectors/{name}/config` (and `/config/history[/{commit}]`,
   `/config/diff`) redact every `HIDDEN_FIELDS` value as `"********"` for
   **all** roles including `admin` — secrets are write-only through this API,
   not plaintext. An agent that trusts the current wording will treat
   `"********"` as a real credential value (e.g. echo it into a workflow, or
   conclude the field is literally set to eight asterisks) instead of
   recognizing it as the redaction placeholder that must be preserved
   unchanged on merge-on-write `PUT`.
2. **The `agent` role itself is undocumented.** Этап 3
   (`docs/compose/reports/agent-devloop-stage3.md`) introduced the RBAC role
   the agent actually authenticates as, with a specific, non-obvious
   boundary (code + jobs, not user/key/audit/transfer administration). The
   prompt never states this, so the agent has no way to predict a `403`
   before hitting one.
3. **B3 (v0.14) carved a further, counter-intuitive exception out of that
   role.** `PUT /connectors/{name}/code` is gated on the literal string
   `"admin"` (`orchestrator/api/connectors.py:519`), not the `_ADMIN` tuple
   that includes `agent` everywhere else in that router (create, delete,
   `PUT /config`, restore code, restore config). This is the **one** write
   endpoint in the entire actions/connectors/workflows surface where `agent`
   is excluded despite being able to write code everywhere else — worth
   calling out explicitly, because "agent can write code" is otherwise true
   almost everywhere and this is the one silent exception (verified against
   current source, see [S3]).
4. Nothing in the prompt states which endpoints are off-limits at all
   (`/auth/*`, `/audit-log`, `/transfer/*`, `PUT /prompts/user`) — an agent
   discovering this only via live `403`s wastes turns and, worse, might
   assume a `403` means a bug rather than an intentional boundary.

## [S2] Solution overview

Edit `orchestrator/prompts/system_prompt.md` only. No code, no new
endpoint, no schema change — this is a content correction plus one new
section, following the doc's existing tone and numbering style (short
prose sections, `##`, no code changes referenced that don't exist).

1. Fix §6 (risks) — replace the "P6 plaintext" claim with the current
   write-only/redaction behavior and its two practical consequences (never
   treat `"********"` as a real value; changing a hidden field's real value
   needs literal `admin`, `agent` gets `403`).
2. Add a new section, placed right after §2 (entity contracts) and before
   the dev-loop section, titled "Your access (role `agent`)" — states the
   role name, gives the one-line boundary ("code + jobs, not
   administration"), and lists the excluded endpoints by prefix so the
   agent can recognize a `403` as expected rather than investigate it.
3. Within that new section (or as a callout in §2, whichever reads better
   in context — decided during implementation), state the B3 exception:
   `PUT /connectors/{name}/code` needs a human/admin; connector *config*
   (non-hidden fields), creation, deletion, and restore of both code and
   config remain available to `agent`.
4. Renumber existing §5/§6 to §6/§7 to make room; no other section's
   content changes.

## [S3] Facts verified against current source (not re-derived from memory)

Read directly from the files below on 2026-07-29, current `main`:

| File | Constant | Members | What it gates |
|---|---|---|---|
| `orchestrator/api/actions.py:22-23` | `_RO` / `_ADMIN` | `+agent` both | list/get/describe/history/diff (`_RO`); `PUT`/`DELETE`/restore (`_ADMIN`) |
| `orchestrator/api/connectors.py:29-31` | `_RO` / `_RW` / `_ADMIN` | `+agent` all three | `_RO`: list/get/describe/schema/history/diff/config-read. `_RW`: OpenAPI preview. `_ADMIN`: generate, create, `DELETE`, `PUT /config`, restore code+config |
| `orchestrator/api/connectors.py:519` | literal `"admin"` | **not** `agent` | `PUT /{name}/code` only — B3 |
| `orchestrator/api/workflows.py:18-20` | `_RO` / `_RW` / `_ADMIN` | `+agent` all three | `_RO`: list/get/history/diff. `_RW`: enable/disable/reload. `_ADMIN`: `PUT`/`DELETE` code, restore |
| `orchestrator/api/jobs.py:13-15` | `_RO` / `_RW` / `_ANALYST` | `+agent` all three | `_RO`: list/get. `_RW`: create job. `_ANALYST`: cancel |
| `orchestrator/api/logs.py:13` | `_RW` | `+agent` | job log / log stream |
| `orchestrator/api/tools.py:9`, `status.py:7` | `_RO` | `+agent` | `/tools`, `/status` |
| `orchestrator/api/prompts.py:12-13` | `_RO` `+agent` / `_ADMIN` **without** agent | `GET /prompts/system`, `GET /prompts/user` readable; `PUT /prompts/user` is not |
| `orchestrator/api/audit.py:30` | literal `"admin"` | excludes agent | `GET /audit-log` |
| `orchestrator/api/transfer.py:24` | literal `"admin"` (router-level) | excludes agent | all of `/transfer/*` |
| `orchestrator/auth/router.py:96,108,117,136,152,160` | literal `"admin"` | excludes agent | `/auth/users`, `/auth/keys` (all methods) |
| `docs/agents/security-patterns.md` §"Connector secret redaction" | — | — | confirms `"********"` redaction is current behavior for all roles, merge-on-write semantics, and the B3 rationale |

This table is the source for the new section's content — no invented
endpoints, no paraphrase of stale docs.

## [S3a] Addendum — Tool as a fourth, read-only entity

Follow-up request during implementation: §2 listed only the three
API-writable entities (Action/Connector/Workflow) and never named `Tool`
(`soar/tools/`) at all, even though §5 already told the agent to call
`GET /tools` for discovery — the concept was used before it was
introduced. Per `AGENTS.md`'s "движок vs поведение" principle, `Tool` is
architecturally not a peer of the other three: no `PUT`/`DELETE` route
exists for it under any role (`AGENTS.md` §"Архитектурный принцип" —
"`/tools` — без PUT/DELETE... tools не является редактируемым через API
поведением, это часть движка"). Adding it as an unqualified fourth
bullet under "entity contracts" would misstate this. Resolution: rename
§2 from "The three entity contracts" to "Entity contracts", add Tool as
a fourth bullet explicitly marked read-only/no-write-route, and narrow
the "read/written through symmetric API groups" paragraph that follows
to name only the three CRUD entities it actually describes.

## [S4] Non-goals

- Not touching `orchestrator/prompts/user_prompt.md` (operator-supplied,
  admin-editable, not part of this doc's scope).
- Not adding a one-shot example library — still explicitly deferred
  per `UPGRADE.md` Часть 3 (P4-примеры), unrelated to this staleness fix.
- Not changing any RBAC code, endpoint, or test — this spec only corrects
  what the prompt *says* about behavior that already exists and is already
  tested (Этап 3, B2/B3 in v0.14).
- Not restructuring the whole file — only §6 content-fix, one new section,
  and the renumbering that implies.

## [S5] Success criteria

- [ ] §6 no longer claims connector secrets are returned in plaintext;
      states the actual write-only/redaction behavior and the
      `"********"` placeholder semantics.
- [ ] A new section states the `agent` role's boundary in one place: what
      it can do (code + jobs across actions/workflows/connectors, minus
      the B3 exception) and the four endpoint groups it cannot reach
      (`/auth/*`, `/audit-log`, `/transfer/*`, `PUT /prompts/user`).
- [ ] The B3 exception (`PUT /connectors/{name}/code` needs literal admin)
      is stated explicitly, distinguishing it from `PUT /config` and from
      connector create/delete/restore, which remain available to `agent`.
- [ ] `GET /prompts/system` (manually or via test) returns the updated
      content — no code path caches or duplicates this file, so no other
      change is required for it to take effect.
