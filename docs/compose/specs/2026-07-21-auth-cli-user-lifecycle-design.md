# Auth CLI: table_prefix bug + user deactivation

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/auth-cli-user-lifecycle.md)
>
> Plan: `docs/compose/plans/2026-07-21-auth-cli-user-lifecycle.md`

## [S1] Problem

Two gaps surfaced while documenting auth ops in `README.md`:

1. **Bug — `orchestrator/auth/cli.py` ignores `database.table_prefix`.**
   `main.py` calls `configure_table_prefix(config.database.table_prefix)`
   before anything imports `orchestrator.auth.models` (required — prefix is
   baked into `__tablename__` at class-definition time, see
   `orchestrator/db/base.py`). `cli.py::_create_user` never calls
   `configure_table_prefix()` at all, and resolves its DB URL from an
   ad-hoc `SOAR_DB_URL` env var instead of `config.yaml`/`SOAR_CONFIG` (the
   single source of truth the running app itself uses, per
   `orchestrator/config.py::load_config`). On any deployment with a
   non-empty `table_prefix` (e.g. `deploy/stage`, `table_prefix: "stage_"`),
   `create-user` silently writes into the unprefixed `users` table — a
   table the running app never queries (it reads `stage_users`). The user
   is created, looks successful, and can never log in.

2. **Missing feature — no way to remove a user's access.** Neither the CLI
   nor `orchestrator/auth/router.py` exposes anything to disable a user.
   `User.is_active` exists and is already enforced in
   `service.authenticate_user()` (`WHERE ... is_active == True`), but
   nothing ever sets it to `false`. `create-user` is the only lifecycle
   operation that exists today.

## [S2] Solution

### Fix: CLI reads the same config the app reads

`cli.py` resolves `SOAR_CONFIG` (default `config.yaml`) via
`orchestrator.config.load_config()` — exactly like `main.py` — and calls
`configure_table_prefix(config.database.table_prefix)` **before** importing
`orchestrator.auth.models`. DB URL defaults to `config.database.url`;
an optional `--db-url` flag can still override it for one-off scripting
(e.g. no config file present). `SOAR_DB_URL` env var support is dropped —
it's undocumented anywhere except the README note added in the previous
turn (being corrected here) and is the actual root cause of the bug
(a second, independent source of truth for the DB connection).

### Feature: `deactivate-user` / `activate-user` CLI subcommands

Soft-delete via the existing `User.is_active` flag — no schema change.
Mirrors `create-user`: CLI-only (no `/auth/users` API endpoint), consistent
with the existing design decision that user provisioning is an ops
out-of-band action, not self-service via API (unlike API keys, which are
already fully CRUD over `/auth/keys` for admins). New
`orchestrator.auth.service.set_user_active(db, username, is_active) -> User`
raises `LookupError` if the username doesn't exist; CLI catches it and
exits non-zero with a clear message.

```bash
python -m orchestrator.auth.cli deactivate-user --username alice
python -m orchestrator.auth.cli activate-user --username alice
```

Deactivating a user blocks future `/auth/login` calls immediately, but — as
already documented for role changes — an **already-issued access token
stays valid until its `exp`** (up to `access_token_ttl`, default 30 min):
`get_current_user` trusts the JWT payload and never re-checks `is_active`
per request (stateless by design, see prior conversation on the JWT
mechanism). This is an existing, accepted tradeoff — not something this
change alters. Existing refresh tokens are **not** auto-revoked either;
out of scope here (would need a lookup join from `refresh_tokens` to
`users.is_active` in `rotate_refresh_token`, a separate concern from the
two bugs this spec fixes — noted as a follow-up, not blocking).

## [S3] Non-goals

- No `/auth/users` API endpoints (would need a design decision on API vs.
  CLI provisioning that's out of scope for a bugfix+small-feature pass).
- No auto-revocation of a deactivated user's outstanding refresh tokens or
  in-flight access tokens.
- No `list-users` subcommand — not required to deactivate by username, and
  not part of what was flagged.

## [S4] Testing strategy

- `tests/orchestrator/auth/test_cli.py` (new):
  - Subprocess end-to-end test (mirrors `tests/orchestrator/
    test_table_prefix.py`'s isolation approach, needed because
    `configure_table_prefix()` is process-global and fixed at first model
    import): write a temp `config.yaml` with `database.url` pointing at a
    temp SQLite file and `database.table_prefix: "cli_"`, run
    `python -m orchestrator.auth.cli create-user` as a subprocess with
    `SOAR_CONFIG` set to that file, then open the SQLite file directly and
    assert the row exists in `cli_users` (not `users`).
  - Unit tests (direct async calls, no subprocess needed — `is_active`
    doesn't have the import-time constraint) for
    `service.set_user_active()`: activate/deactivate round-trip, and
    `LookupError` on unknown username.
  - `tests/orchestrator/api/test_auth_api.py`: add a case that a
    deactivated user gets 401 from `/auth/login`.

## [S5] Success criteria

- [ ] `create-user` run against a `table_prefix`-configured DB lands rows in
      the prefixed table the running app actually reads
- [ ] `deactivate-user` / `activate-user` work end-to-end; deactivated user
      can't log in
- [ ] `README.md` auth section reflects the fixed CLI behavior and the new
      subcommands; the now-stale table_prefix caveat and "not implemented"
      deletion note are replaced
- [ ] Full test suite + `ruff check .` pass
