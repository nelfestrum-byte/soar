---
feature: auth-cli-user-lifecycle
status: delivered
specs:
  - docs/compose/specs/2026-07-21-auth-cli-user-lifecycle-design.md
plans:
  - docs/compose/plans/2026-07-21-auth-cli-user-lifecycle.md
branch: main
commits: pending
---

# Auth CLI: table_prefix bug + user deactivation — Final Report

## What Was Built

Fixed a bug where `orchestrator/auth/cli.py` could silently create users in
the wrong database table on any deployment using `database.table_prefix`
(e.g. `deploy/stage`), and added the missing ability to deactivate/reactivate
a user's access — previously the only lifecycle operation was `create-user`.

## What Changed

### Bug fix: CLI now shares config resolution with the running app

`orchestrator/auth/cli.py` used to resolve its DB connection from an ad-hoc
`SOAR_DB_URL` env var and never called `configure_table_prefix()`. On a
`table_prefix`-configured DB (stage: `table_prefix: "stage_"`), `create-user`
wrote into the unprefixed `users` table — a table the running service never
reads (it reads `stage_users`). The command reported success; the user could
never log in.

Fix: `cli.py` now calls `orchestrator.config.load_config(SOAR_CONFIG)` —
exactly what `main.py` does — and `configure_table_prefix(config.database
.table_prefix)` before importing `orchestrator.auth.models`. `database.url`
from the same config is the default DB target; an optional `--db-url` flag
remains for one-off overrides. `SOAR_DB_URL` was removed — it was the second,
independent source of truth that caused the drift.

### New: `deactivate-user` / `activate-user`

Soft-delete via the existing `User.is_active` column (already enforced in
`service.authenticate_user`, just never had a way to be set to `false`).
New `orchestrator.auth.service.set_user_active(db, username, is_active)`
raises `LookupError` for an unknown username; the CLI prints to stderr and
exits 1.

```bash
python -m orchestrator.auth.cli deactivate-user --username alice
python -m orchestrator.auth.cli activate-user --username alice
```

Deliberately CLI-only, no `/auth/users` API endpoint — mirrors the existing
`create-user` design decision (user provisioning is an ops action, unlike
API keys which are full CRUD over `/auth/keys`). No auto-revocation of
outstanding access/refresh tokens for a deactivated user — noted as a
known, pre-existing tradeoff (access tokens are stateless JWTs, checked
against `is_active` only at `/auth/login` time), not something this change
introduces or was scoped to fix.

### Docs

`README.md` auth section and `AGENTS.md` updated to describe the fixed CLI
behavior and the two new subcommands, replacing the stale
"known limitation" / "not implemented" notes written before this fix.

## Verification

- New tests: `tests/orchestrator/auth/test_service.py` (4 cases —
  activate/deactivate round-trip, unknown-user `LookupError`, deactivated
  user fails `authenticate_user`), `tests/orchestrator/auth/test_cli.py`
  (3 subprocess end-to-end cases — table_prefix applied correctly,
  deactivate/activate via CLI, unknown-user failure), plus one added case
  in `tests/orchestrator/api/test_auth_api.py` (deactivated user gets 401
  from `/auth/login`).
- Full suite: `python -m pytest tests/ -q` — 372 passed, 1 pre-existing
  unrelated failure (`test_openapi.py::test_generate_config`, openapi
  connector generator, untouched by this change), 5 pre-existing collection
  errors from missing optional connector deps (misp/mysql/shodan/smb/winrm)
  in this environment — none related to auth.
- `ruff check orchestrator/auth/ tests/orchestrator/auth/
  tests/orchestrator/api/test_auth_api.py` — clean.
