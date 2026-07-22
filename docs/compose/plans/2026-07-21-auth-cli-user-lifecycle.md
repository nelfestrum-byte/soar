# Plan: Auth CLI table_prefix bug + user deactivation

Spec: [`docs/compose/specs/2026-07-21-auth-cli-user-lifecycle-design.md`](../specs/2026-07-21-auth-cli-user-lifecycle-design.md)

## Phase 1 — `set_user_active` service function

- [ ] Add failing test in `tests/orchestrator/auth/test_service.py` (new
  file if it doesn't exist — check first) covering:
  - `set_user_active(db, "alice", False)` sets `is_active = False`, returns
    the `User`
  - `set_user_active(db, "alice", True)` flips it back
  - `set_user_active(db, "ghost", False)` raises `LookupError`
- [ ] `orchestrator/auth/service.py`: add `set_user_active(db, username,
  is_active) -> User`
- [ ] Run `python -m pytest tests/orchestrator/auth/ -v`

## Phase 2 — Deactivated user can't log in

- [ ] Add failing test to `tests/orchestrator/api/test_auth_api.py`:
  create a user, deactivate via `service.set_user_active`, assert
  `POST /auth/login` returns 401
- [ ] Verify against current code — `authenticate_user` already filters
  `is_active == True`, so this should pass once Phase 1 lands with no
  router/dependency changes needed. If it doesn't pass, investigate before
  moving on (don't assume).
- [ ] Run `python -m pytest tests/orchestrator/api/test_auth_api.py -v`

## Phase 3 — Fix CLI: config-driven DB URL + table_prefix

- [ ] Write `tests/orchestrator/auth/test_cli.py` (new). Subprocess test
  (isolation required — table prefix is fixed at first model import in a
  process, same constraint as `test_table_prefix.py`):
  1. Write a temp dir with a `config.yaml`:
     ```yaml
     database:
       url: "sqlite+aiosqlite:///<tmpdir>/cli_test.db"
       table_prefix: "cli_"
     ```
  2. Run `subprocess.run([sys.executable, "-m", "orchestrator.auth.cli",
     "create-user", "--username", "clitest", "--password", "x",
     "--role", "admin"], env={..., "SOAR_CONFIG": <path>}, cwd=repo_root)`
  3. Assert `returncode == 0`
  4. Open `<tmpdir>/cli_test.db` directly with `sqlite3` (stdlib, sync —
     the subprocess already exited, no async needed), assert:
     - `cli_users` table exists with the row
     - plain `users` table does **not** exist (proves prefix was applied,
       not just present alongside an unprefixed leftover)
  This fails now — `cli.py` uses `SOAR_DB_URL`/no prefix, so it would
  create plain `users` in a default `./soar.db`, not
  `<tmpdir>/cli_test.db`.
- [ ] `orchestrator/auth/cli.py`:
  - Import `orchestrator.config.load_config` and
    `orchestrator.db.base.configure_table_prefix` at module top (before
    the lazy in-function imports of `orchestrator.auth.models` — same
    ordering constraint as `main.py`)
  - `_create_user`: accept `config` (an `OrchestratorConfig`) instead of
    raw `db_url`; call `configure_table_prefix(config.database.table_prefix)`
    before importing `orchestrator.auth.models`; use
    `config.database.url` unless `--db-url` override given
  - `main()`: resolve `config = load_config(os.environ.get("SOAR_CONFIG",
    "config.yaml"))` once, before dispatching to any subcommand handler;
    add `--db-url` optional override arg to `create-user` (and the new
    subcommands from Phase 4)
  - Remove `SOAR_DB_URL` env var read entirely
- [ ] Run `python -m pytest tests/orchestrator/auth/test_cli.py -v`
- [ ] Run full auth suite to confirm no regression on the default
  (no-config, empty-prefix) path:
  `python -m pytest tests/orchestrator/auth/ tests/orchestrator/api/test_auth_api.py -v`

## Phase 4 — `deactivate-user` / `activate-user` CLI subcommands

- [ ] Extend `tests/orchestrator/auth/test_cli.py`: subprocess test
  creating a user then deactivating it via
  `python -m orchestrator.auth.cli deactivate-user --username clitest`
  against the same temp config; assert `is_active = 0` in the sqlite row.
  Also cover unknown username → non-zero exit, stderr mentions the
  username.
- [ ] `orchestrator/auth/cli.py`: add `deactivate-user` and `activate-user`
  subparsers (`--username` required, reuse the same config/prefix wiring
  from Phase 3), calling `service.set_user_active(session, username,
  False/True)`; catch `LookupError` → print to stderr, `sys.exit(1)`
- [ ] Run `python -m pytest tests/orchestrator/auth/test_cli.py -v`

## Phase 5 — Docs

- [ ] `README.md` `auth` section:
  - Replace the `SOAR_DB_URL` example and the table_prefix "known
    limitation" callout — CLI now reads `SOAR_CONFIG` like the app, no
    caveat needed
  - Replace the "deletion not implemented" paragraph with
    `deactivate-user` / `activate-user` usage, and the note about
    already-issued tokens/refresh tokens surviving until TTL/explicit
    logout (per spec [S2])
- [ ] `AGENTS.md`: update the `CLI создания пользователя` line(s) (File
  map + Authentication section) to mention `deactivate-user`/
  `activate-user` and that the CLI now shares config resolution with the
  app (grep `create-user` in AGENTS.md first to find all mentions)
- [ ] Write `docs/compose/reports/auth-cli-user-lifecycle.md` per repo
  convention (frontmatter, what changed, verification performed)

## Test commands (full pass before considering done)

```bash
python -m pytest tests/ -v
ruff check .
```
