---
feature: agent-devloop-stage3
date: 2026-07-22
spec: docs/compose/specs/2026-07-22-agent-devloop-stage3-design.md
plan: docs/compose/plans/2026-07-22-agent-devloop-stage3.md
---

# Report: Agent Dev-Loop — Этап 3

## What was built

Closes P7 from `UPGRADE.md`: a new RBAC role `agent` that can write
workflow/action/connector code and run/manage jobs, without the
user-management/API-key/audit-log access that came bundled with `admin`
before this change. Roles are plain strings in this codebase (no enum, no
schema migration), so this is purely an application-layer change across
three validation chokepoints ([S3]) and a table of tuple constants ([S4]).

**[S3] — role validation, three independent lists (all extended `+ "agent"`
per spec, not unified — out of scope per [S7]):**
- `orchestrator/auth/service.py` — `ROLES` set, used by `UserCreate`/
  `UserUpdate` pydantic validators for `POST /auth/users`/`PATCH
  /auth/users/{id}`.
- `orchestrator/auth/cli.py` — `argparse` `choices` on `create-user --role`.
- `deploy/soarctl_lib/users.py` — `_ROLES` tuple + `ValueError` guard in
  `create()`.

`ApiKeyCreate.role` has no validator (`POST /auth/keys` already accepted
any string) — confirmed unchanged, no edit needed there.

**[S4] — tuple constants, `agent` added exactly per the spec's table:**

| File | Constants touched |
|---|---|
| `orchestrator/api/actions.py` | `_RO`, `_ADMIN` |
| `orchestrator/api/connectors.py` | `_RO`, `_RW`, `_ADMIN` |
| `orchestrator/api/workflows.py` | `_RO`, `_RW`, `_ADMIN` |
| `orchestrator/api/jobs.py` | `_RO`, `_RW`, `_ANALYST` |
| `orchestrator/api/logs.py` | `_RW` |
| `orchestrator/api/tools.py` | `_RO` |
| `orchestrator/api/status.py` | `_RO` |
| `orchestrator/api/prompts.py` | `_RO` only — `_ADMIN` (`PUT /prompts/user`) deliberately left untouched |

Not touched, as specified: `orchestrator/api/audit.py`,
`orchestrator/api/transfer.py`, `orchestrator/auth/router.py` (`/auth/keys`,
`/auth/users`) — all use `require_role("admin")` with the literal string
directly, no shared tuple, so `agent` is excluded automatically.

**Docs** (`AGENTS.md`, `docs/agents/security-patterns.md`,
`README.md`): role list extended `admin`/`analyst`/`viewer`/`service` →
`+ agent`, with a one-line description of what `agent` can/can't do,
matching each file's existing style.

## Phase 1 audit findings (S5)

`grep -rn 'require_role(' orchestrator/`, filtered to literal `"admin"`
calls (not `*_ADMIN`/`*_RO`/`*_RW`/`*_ANALYST` tuple unpacking) found
exactly the set the spec's [S4] "явно не трогаем" list predicted, no
7th/unexpected location:

- `orchestrator/api/audit.py:30` — `GET /audit-log`
- `orchestrator/api/transfer.py:15` — router-level, covers all `/transfer/*`
- `orchestrator/auth/router.py:96,108,117,136,152,160` — six route-level
  dependencies, covering `/auth/keys` (POST/GET/DELETE) and `/auth/users`
  (POST/GET/PATCH)

No regression/new-code finding to resolve before proceeding — audit
matched spec expectations exactly.

## Verification

- `python -m pytest tests/orchestrator/ tests/soar/ tests/deploy/ -q
  --continue-on-collection-errors`: **561 passed, 1 skipped, 1 failed**,
  plus 5 pre-existing collection errors. All pre-existing and unrelated to
  this work, confirmed by inspecting each: `test_openapi.py::
  test_generate_config` (same failure documented in the Stage 1/2 reports)
  and 5 connector test modules failing to *collect* for missing optional
  third-party deps (`pymisp`, `pymysql`, `shodan`, `smbprotocol`,
  `winrm`) — none of the affected files were touched by this change.
- `ruff check orchestrator/ soar/ deploy/`: 8 findings total, all
  pre-existing outside this work's files (`subprocess_runner.py`,
  `active_directory.py`, `wazuh.py`, plus 2 `B904` in `connectors.py`
  documented pre-existing in the Stage 1/2 reports). Ran `ruff check` on
  just the 11 files this stage touched — the only findings were the 2
  pre-existing `B904`s in `connectors.py`, at lines untouched by this
  diff (confirmed via `git diff`).
- New/extended test files: `tests/orchestrator/auth/test_service_roles.py`
  (new — `UserCreate`/`UserUpdate` accept `role="agent"`),
  `tests/deploy/test_soarctl_users.py` (extended — `create(role="agent")`
  argv), `tests/orchestrator/api/test_agent_role_rbac.py` (new, 26 cases —
  one representative request per `_RO`/`_RW`/`_ADMIN`/`_ANALYST`
  constant that gained `agent`, `403` checks on the six untouched
  admin-literal routes + `PUT /prompts/user`, and 3 regression cases for
  `viewer`/`analyst`/`service` unaffected access), `tests/orchestrator/
  api/test_auth_api.py` (extended — `test_admin_can_create_agent_user`,
  `test_admin_can_create_agent_api_key`, plus 6 end-to-end cases using a
  **real JWT** obtained via `/auth/login` for an `agent`-role user hitting
  `/status`, `POST /jobs`, and the four excluded routes, rather than only
  the DI-override style used in `test_agent_role_rbac.py`).
- Test-first was followed for both phases: ran the new Phase 2 tests
  (`test_service_roles.py`, soarctl positive case) before touching
  `ROLES`/`choices`/`_ROLES` — all 3 failed as expected; ran the new
  Phase 3 RBAC test file before touching the tuple constants — 18 of 26
  failed as expected (the other 8 were regression/negative cases already
  passing pre-change).
- **[S8] success criteria — verified one by one:**
  - Create a user or API key with role `agent` via `POST /auth/users`
    and `POST /auth/keys` — verified by `test_admin_can_create_agent_user`,
    `test_admin_can_create_agent_api_key` (real HTTP through the FastAPI
    test client). CLI (`orchestrator/auth/cli.py create-user --role
    agent` / `soarctl users create --role agent`) — verified at the
    argv-construction level via `test_create_argv_agent_role` and the
    `argparse choices` edit; not run against a live container (no deploy
    environment available in this sandbox), consistent with how the CLI
    path is tested elsewhere in this repo.
  - `agent` role gets `200`/`202` on `PUT`/`DELETE`/`restore` for
    actions/connectors/workflows, `POST /jobs`, `POST
    /jobs/{id}/cancel`, `GET /logs/{job_id}`, and all `_RO` routes
    including `describe`/`/prompts/system`/`/prompts/user` (GET) —
    verified by real HTTP requests in `test_agent_role_rbac.py` (DI
    override) and `test_auth_api.py` (real JWT for `/status`, `POST
    /jobs`).
  - `agent` role gets `403` on `/auth/users`, `/auth/keys`,
    `/audit-log`, `/transfer/*`, `PUT /prompts/user` — verified by real
    HTTP requests in both test files (DI override and real JWT).
  - `viewer`/`analyst`/`service`/`admin` behavior unchanged — the full
    pre-existing orchestrator suite (371 tests) passes unmodified, plus
    3 explicit regression cases added in `test_agent_role_rbac.py`.
  - All existing tests pass; new tests cover [S3]–[S4] — confirmed above.

## Notable deviations from the plan

- **Found and worked around a pre-existing bug, did not fix it.** While
  writing `test_agent_can_restore_workflow_code`, a single-PUT-then-
  restore-to-that-same-commit pattern (which no existing test in this
  repo exercises — every existing workflow/action/connector restore test
  does two writes first) surfaced a real bug in `GitManager.commit()`:
  when `load_workflow_metas()` leaves `orchestrator_state.yaml` /
  `workflows/__pycache__/` untracked, git's no-op-commit message changes
  from `"nothing to commit, working tree clean"` to `"nothing added to
  commit but untracked files present"` — a phrasing the `"nothing to
  commit" in combined` check doesn't match, so the no-op `RuntimeError`
  propagates and `restore_version` turns it into a spurious `404`. This
  is already documented as known limitation #7 in `AGENTS.md` ("`GitManager
  .commit()` не распознаёт все формулировки 'nothing to commit'"), is
  unrelated to RBAC/roles, and fixing it was out of this stage's scope
  per `CLAUDE.md`'s "don't refactor beyond the task" rule. Fixed the test
  instead, to match the established two-write-then-restore convention
  used by every other restore test in this repo.
- **Branch/worktree housekeeping.** The task's target path
  (`c:\Users\avb\projects\soar`) is a shared checkout also used by other
  concurrent stage worktrees; an initial `git checkout -b
  agent-devloop-stage3` was run there by mistake (sandbox editing is
  restricted to the assigned worktree, so no file edits happened on that
  checkout). Reverted: switched the shared checkout back to `main`,
  deleted the stray branch pointer, and created `agent-devloop-stage3`
  properly inside the assigned worktree, off the worktree's local `main`
  ref (which already had Stage 1+2 merged, `f4f2cf5`). No work was lost;
  the shared checkout's branch was identical to `main` at the time of the
  revert.
- **README.md role list, beyond the plan's explicit scope.** The spec's
  [S4] table only covers `orchestrator/api/`. Grepping for the four
  existing role names together found one clearly load-bearing,
  user-facing doc list outside that scope: `README.md`'s "Роли: `admin`,
  `analyst`, `viewer`, `service`." line — updated for consistency with
  the same one-line `agent` description used in `AGENTS.md`/
  `security-patterns.md`. `CHANGELOG.md`'s `v0.5.1` entry also lists the
  four original roles but was **not** touched — it's a historical record
  of what shipped in that version, not a living reference.
- No other deviations — [S3]/[S4] were implemented exactly as specified,
  including the exact tuple contents and the explicit non-edits
  (`prompts.py`'s `_ADMIN`, and the six admin-literal routes).
