---
feature: deploy-cli
date: 2026-07-22
spec: docs/compose/specs/2026-07-22-deploy-cli-design.md
plan: docs/compose/plans/2026-07-22-deploy-cli.md
---

# Report: Deploy CLI (`soarctl`)

## What was built

A two-layer deploy/lifecycle CLI for distributing and operating a SOAR
instance under an air-gap-first model (no image registry — build on a
connected machine, transfer a self-contained bundle, install offline):

- **`deploy/prod/`** — a new, distributable compose profile alongside the
  existing `deploy/stage/` (untouched, still the internal QA stack):
  `docker-compose.yml` references `image: soar-orchestrator:${SOAR_VERSION}`
  / `soar-ui:${SOAR_VERSION}` instead of `build:`; `config.yaml` is
  bind-mounted (not baked into the image, unlike stage); named volumes are
  fixed (`soar-data`, `soar-logs`, `soar-redis-data`, `soar-postgres-data`)
  so backup tooling can find them without depending on compose project
  naming. `Dockerfile.orchestrator`/`Dockerfile.ui`/`nginx.conf` mirror
  stage's, minus the `COPY config.yaml` step. `config.yaml.template` holds
  `${AUTH_SECRET_KEY}`/`${POSTGRES_PASSWORD}` placeholders resolved by
  `soarctl init`, not by docker compose (confirmed
  `orchestrator/config.py::load_config` does a plain `yaml.safe_load`, no
  env expansion — the two substitution mechanisms, compose's `.env` and
  soarctl's template render, are intentionally separate).
- **`deploy/soarctl_lib/`** — the library: `runner.py` (single
  `subprocess` choke point), `paths.py`, `env.py` (secret generation +
  template render), `compose.py`, `status.py`, `migrate.py`, `users.py`
  (proxies the existing `orchestrator.auth.cli`, unchanged), `backup.py`,
  `bundle.py` (package/install), `doctor.py`, `cli.py` (argparse
  dispatch). Every module builds argv lists and calls `runner.run()` —
  nothing else touches `subprocess` directly.
- **`deploy/soarctl`** — thin executable shim (`chmod +x`, stdlib only)
  that adds its own directory to `sys.path` and calls `soarctl_lib.cli.main()`.
  Works identically from a source checkout (imported as `deploy.soarctl_lib`
  in dev/tests) and from an installed bundle (imported as bare
  `soarctl_lib`, since only that directory — not `deploy/` — is copied) —
  every intra-package import in `soarctl_lib/*.py` is relative (`from
  .compose import ...`) specifically so both contexts resolve.
- **`VERSION`** file at repo root (`0.9.0`), `deploy/.gitignore` extended
  (`prod/config.yaml`, `prod/.env`, `*.tar.gz`, `/prod/build/`).
- **`deploy/prod/README.md`** — operator-facing walkthrough (package →
  install → doctor → init → up → migrate → users create → day-2 ops →
  upgrade path).
- **`tests/deploy/`** — 70 tests across 11 files (renamed with a
  `test_soarctl_*` prefix — plain `test_cli.py`/`test_status.py` collided
  with existing `tests/orchestrator/auth/test_cli.py` /
  `tests/orchestrator/api/test_status.py` under pytest's flat,
  `__init__.py`-less module namespace).

## Deviations from the plan/spec

- **`soarctl users` has no `list`**, only `create`/`deactivate`/`activate`
  — the underlying `orchestrator.auth.cli` doesn't have one either (a
  prior spec, `2026-07-21-auth-cli-user-lifecycle-design.md` [S3],
  deliberately left listing to `/auth/users`). The deploy-cli spec's
  command table listed `list` by oversight; the plan already flagged and
  corrected this before implementation.
- **Volume backup avoids bind-mounting a host directory into the alpine
  helper container.** The spec didn't specify the mechanism; implementing
  it surfaced that `-v <host>:<container>` bind mounts are ambiguous to
  parse back out on Windows (a drive letter's `:` collides with the
  mount syntax's own separator). `backup.py` instead pipes the volume tar
  over the helper container's stdout/stdin (`docker run ... tar czf - ...`
  captured as bytes, `runner.run(..., text=False)`), avoiding host-path
  translation entirely — also simpler and equally portable.
- **`soarctl install` on an already-`init`-ed instance now bumps only
  `SOAR_VERSION` in `.env`**, added during implementation (not in the
  original plan). Without it, upgrading would have required either
  manually editing `.env` before every `up` (documented as a workaround
  first, then judged not good enough to ship) or `init --force`, which
  regenerates `AUTH_SECRET_KEY`/`POSTGRES_PASSWORD` and would lock the
  instance out of its own Postgres database. `env.update_version()` +
  test coverage added; `bundle.install()` calls it when `.env` already
  exists.

## Verification

- `python -m pytest tests/deploy/ -v` — 70 passed.
- `python -m pytest tests/ -q` (excluding 5 files that fail even in
  isolation on a clean checkout, missing optional deps unrelated to this
  change: `pymisp`, mysql/shodan/smb_rpc/winrm connector libs) — 461
  passed, 1 skipped, 1 pre-existing failure (`test_openapi.py::
  test_generate_config`, confirmed unrelated — fails identically without
  any of this session's changes applied).
- `ruff check deploy/soarctl deploy/soarctl_lib tests/deploy` — clean.
  `ruff check .` on the full repo shows 37 pre-existing findings, none in
  the new code (confirmed via path grep) — left untouched per "не
  рефакторить вне задачи".
- Added `deploy` to `known-first-party` in `pyproject.toml`'s isort config.
- Manual smoke test, real Docker (Docker Desktop, compose v5.1.3):
  - `soarctl package --version 0.9.0-smoke` — real `docker build` for
    `soar-orchestrator`/`soar-ui` from the new `deploy/prod/Dockerfile.*`,
    real `docker pull` of `redis:7-alpine`/`postgres:16-alpine`, real
    `docker save` of all four, real tar assembly — produced a 274MB
    bundle. **Caught a real bug this way**: `shutil.copytree()` was
    copying `soarctl_lib/__pycache__/*.pyc` into the bundle (stale
    bytecode, no unit test had a `__pycache__` present to catch it). Fixed
    with `shutil.copytree(..., ignore=shutil.ignore_patterns("__pycache__",
    "*.pyc"))` in `bundle.py`, added a regression test in
    `test_soarctl_bundle.py` (creates a fake `__pycache__` in the test
    fixture, asserts no `__pycache__` entries in the produced tar),
    re-ran the real build to confirm the fix.
  - `soarctl install <bundle> --dir <scratch>` — real `docker load`;
    confirmed both images present in `docker images` afterward, confirmed
    `images.tar` was deleted post-load.
  - `soarctl init` + `soarctl doctor` against the installed instance —
    secrets generated at correct lengths (64/32/32 hex chars), `config.yaml`
    rendered with no leftover `${...}` placeholders, `.env` correct;
    doctor correctly reported docker/compose OK, disk OK, and **correctly
    flagged** ports 8000/3000 as busy (expected — `deploy/stage` was
    already running in this environment).
  - Cleaned up the smoke-test images/scratch directories afterward.
- **Full live cycle, second pass** (after `deploy/stage` was deliberately
  torn down with `docker compose down -v` to free ports 8000/3000, at the
  user's explicit request — stage's containers, volumes, and network were
  all removed; stage itself is unaffected on disk and can be brought back
  up from the same compose file whenever needed):
  `package --version 0.9.0-e2e` → `install` → `init` → `doctor` (all OK,
  ports free) → `up` (all four containers healthy) → `status` (`health:
  ok`) → `migrate --fresh` (`alembic stamp` → `3067dea7c75b`, matching
  `alembic/versions/` head) → `users create --username admin --role admin`
  (interactive password via stdin) → verified the bootstrapped admin can
  actually **log in** (`POST /auth/login` returned a real access/refresh
  token pair) → `backup create` → inspected the resulting archive: `db.sql`
  contains the `admin` row, `soar-data.tar.gz` present — → `down`. Every
  step exited 0. Cleaned up the smoke instance's images/volumes/scratch
  directory afterward (this session's own test artifacts, not user data).
  This closes the one gap from the first smoke-test pass above.
- **Upgrade scenario, live** (in response to "how do I verify an upgrade
  when the code changes"): tracing through `deploy/prod/README.md`'s
  documented upgrade steps surfaced a real ordering bug — it had `migrate`
  listed *before* `up`, but `migrate` runs `docker compose exec
  orchestrator ...` inside whatever container is currently running; before
  `up` recreates it on the new image, that's still the *old* container,
  so it would apply the *old* image's `alembic/versions/`, not the new
  one's. Fixed the README to `install → up → migrate` and explained why.
  Then verified the corrected order live: packaged `1.0.0-v1`, deployed it
  fully (install/init/up/migrate --fresh/users create --admin), confirmed
  login. Packaged `1.1.0-v2` (same code, standing in for "a new release"
  — proves the mechanics soarctl actually controls, independent of
  whatever a real code diff would contain) and ran `install
  <v2-bundle> --dir <same instance>` **over the live v1 instance**:
  `.env` showed `SOAR_VERSION` bumped to `1.1.0-v2` with
  `AUTH_SECRET_KEY`/`POSTGRES_PASSWORD`/`SOAR_WEBHOOK_TOKEN` byte-for-byte
  unchanged. `soarctl up` afterward showed compose **recreating only**
  `orchestrator`/`ui` (image tag changed) while leaving `postgres`/`redis`
  untouched/running (no tag change, no restart) — `docker compose ps`
  confirmed `orchestrator`/`ui` now on `soar-orchestrator:1.1.0-v2`/
  `soar-ui:1.1.0-v2`. The admin user created under v1, with its original
  password, **logged in successfully post-upgrade** (`/auth/login`
  returned a fresh token pair) — proving Postgres data survives an
  upgrade without needing the volume to be touched at all. `soarctl
  migrate --fresh` re-run afterward was a correctly idempotent no-op
  (already at head). Cleaned up all v1/v2 images, volumes, and the
  scratch directory afterward.

## Known follow-ups (not blocking, not in scope here)

- `soarctl migrate` stays a manual `--fresh`/`--upgrade` choice — the
  underlying `create_all()`-vs-Alembic duality (AGENTS.md → Database
  backend) is unresolved; a future architecture change to drop
  `create_all()` in prod in favor of a pure Alembic path would let this
  become one safe command.
- Multi-instance support is explicitly out of scope — AGENTS.md Known
  Limitations #9.
- `deploy/prod/Dockerfile.ui` and `Dockerfile.orchestrator` still require
  internet during `soarctl package` itself (`npm ci`, `pip install`) —
  by design, per the scoping decision that only the install-side needs to
  be air-gapped, not the build side.
