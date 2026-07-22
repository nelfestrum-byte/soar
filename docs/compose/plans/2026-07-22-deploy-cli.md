# Plan: Deploy CLI (`soarctl`)

Spec: [`docs/compose/specs/2026-07-22-deploy-cli-design.md`](../specs/2026-07-22-deploy-cli-design.md)

Scope note vs. spec table: `soarctl users` ships `create`/`deactivate`/`activate`
only, no `list` — the referenced auth-cli spec ([S3] in
`2026-07-21-auth-cli-user-lifecycle-design.md`) already decided against a
`list-users` CLI subcommand in favor of `/auth/users` (API/UI). `soarctl`
proxies the CLI as-is and shouldn't grow it a feature it doesn't have.

## 0. Repo infra

- [ ] Add `VERSION` file at repo root: `0.9.0`
- [ ] Add `deploy/prod/` gitignore entries to `deploy/.gitignore`:
      `prod/config.yaml`, `prod/.env`, `*.tar.gz`, `/prod/build/`

## 1. `deploy/prod/` compose profile

- [ ] `deploy/prod/Dockerfile.orchestrator` — copy of
      `deploy/stage/Dockerfile.orchestrator` minus the
      `COPY deploy/stage/config.yaml /app/config.yaml` line (config is
      bind-mounted at runtime, never baked into the image — spec [S2]
      "Конфиг/секреты")
- [ ] `deploy/prod/Dockerfile.ui` — copy of `deploy/stage/Dockerfile.ui`,
      references `deploy/prod/nginx.conf`
- [ ] `deploy/prod/nginx.conf` — copy of `deploy/stage/nginx.conf` (no
      changes needed, generic reverse proxy)
- [ ] `deploy/prod/config.yaml.template` — same shape as
      `deploy/stage/config.yaml`, secrets replaced with `${AUTH_SECRET_KEY}`
      / `${POSTGRES_PASSWORD}` placeholders (`string.Template` syntax,
      resolved by `soarctl init`, not by docker compose)
- [ ] `deploy/prod/docker-compose.yml` — redis + postgres + orchestrator +
      ui, `image: soar-orchestrator:${SOAR_VERSION}` /
      `soar-ui:${SOAR_VERSION}` instead of `build:`; orchestrator mounts
      `./config.yaml:/app/config.yaml:ro`; postgres/webhook secrets from
      `.env` (`POSTGRES_PASSWORD`, `SOAR_WEBHOOK_TOKEN`); named volumes
      (`soar-data`, `soar-logs`, `soar-redis-data`, `soar-postgres-data`)
      fixed via `name:` so a backup helper container can find them
      regardless of compose project name (single-instance assumption, see
      AGENTS.md Known Limitations #9)

## 2. `soarctl_lib` — host-layer library (stdlib only)

Test-first per module: write the failing test, then implement.

### 2.1 `deploy/soarctl_lib/runner.py`
- [ ] `tests/deploy/test_runner.py` — `run()` builds subprocess call with
      given argv/cwd and returns `CompletedProcess`; raises on non-zero
      exit unless `check=False`
- [ ] Implement `run(argv: list[str], cwd=None, check=True, env=None) ->
      subprocess.CompletedProcess` — the only place that calls
      `subprocess.run`, everything else builds argv lists and calls this

### 2.2 `deploy/soarctl_lib/paths.py`
- [ ] `tests/deploy/test_paths.py` — `repo_root()` finds the directory
      containing `pyproject.toml` walking up from a given file path;
      `read_version(dir)` reads/strips a `VERSION` file; `instance_dir(args)`
      resolves `--dir` or cwd
- [ ] Implement

### 2.3 `deploy/soarctl_lib/env.py`
- [ ] `tests/deploy/test_env.py` —
  - `generate_secrets()` returns hex strings of the expected lengths, and
    two calls differ (no shared randomness bug)
  - `render_template(text, values)` substitutes `${VAR}` and leaves
    unknown identifiers alone (`string.Template.safe_substitute` semantics
    — do not error on `$` that isn't a placeholder, e.g. inside the
    already-templated DB URL)
  - `init_instance(dir, force=False)` writes `.env` + `config.yaml` from
    `config.yaml.template`; refuses to overwrite an existing `.env` unless
    `force=True`; raises a clear error if `config.yaml.template` is
    missing from `dir`
- [ ] Implement (uses `secrets.token_hex`, `string.Template`)

### 2.4 `deploy/soarctl_lib/compose.py`
- [ ] `tests/deploy/test_compose.py` — argv builders produce the expected
      `["docker", "compose", "-f", <dir>/docker-compose.yml, "--env-file",
      <dir>/.env, ...]` prefix for `up`/`down`/`restart`/`logs`; `up`/`down`
      etc. raise a clear error (not a `docker` traceback) if `.env` is
      missing in the instance dir
- [ ] Implement `up(dir)`, `down(dir)`, `restart(dir)`, `logs(dir,
      service=None)`, `ps(dir)` (used by `status`)

### 2.5 `deploy/soarctl_lib/status.py`
- [ ] `tests/deploy/test_status.py` — `check_health(base_url)` hits
      `GET /health` (mock `urllib.request.urlopen`, no new HTTP dependency)
      and returns ok/error without raising; formats a one-line summary
- [ ] Implement — combines `compose.ps()` output with `/health` (and
      `/status` if `--token` passed)

### 2.6 `deploy/soarctl_lib/migrate.py`
- [ ] `tests/deploy/test_migrate.py` — `stamp_head(dir)` and
      `upgrade_head(dir)` build
      `docker compose ... exec orchestrator python -m alembic {stamp,upgrade} head`
      argvs — two distinct functions, no auto-detect (spec [S3])
- [ ] Implement

### 2.7 `deploy/soarctl_lib/users.py`
- [ ] `tests/deploy/test_users.py` — argv builders for
      `create`/`deactivate`/`activate` proxy to
      `docker compose ... exec orchestrator python -m orchestrator.auth.cli
      <cmd> --username ... [--role ...]`, matching the existing CLI's flags
      exactly (no new flags invented on this layer)
- [ ] Implement

### 2.8 `deploy/soarctl_lib/backup.py`
- [ ] `tests/deploy/test_backup.py` —
  - `create(dir, output)` argv sequence: `pg_dump` via `compose exec -T
    postgres`, then an `alpine` helper container tar'ing the `soar-data`
    volume, then both files combined into one output archive (assert file
    layout inside the produced tar using `tarfile`, with the docker calls
    mocked)
  - `restore(dir, archive)` refuses without an explicit `confirm=True` —
    this is destructive (overwrites DB + workflow data)
- [ ] Implement using `tarfile`/`tempfile` for archive handling, `runner.run`
      for the docker calls

### 2.9 `deploy/soarctl_lib/bundle.py`
- [ ] `tests/deploy/test_bundle.py` —
  - `package(version, output)` argv sequence: build orchestrator/ui images,
    pull `redis:7-alpine`/`postgres:16-alpine`, `docker save` all four into
    a staging dir, then tar the staging dir (compose file, template,
    `soarctl` + `soarctl_lib`, `VERSION`) into `output` — assert the final
    tar's member list, docker calls mocked
  - `install(bundle_path, dest_dir)` extracts the tar into `dest_dir`, then
    `docker load -i dest_dir/images.tar`, then removes `images.tar`
- [ ] Implement

### 2.10 `deploy/soarctl_lib/doctor.py`
- [ ] `tests/deploy/test_doctor.py` — each check is a standalone function
      returning `(ok: bool, message: str)`: `docker` on PATH
      (`shutil.which`), `docker compose version` runs, target ports
      (8000/3000) free (`socket.bind` probe), `.env` present and no
      placeholder values left, free disk space above a floor
      (`shutil.disk_usage`)
- [ ] Implement

## 3. `deploy/soarctl` — CLI entrypoint

- [ ] `tests/deploy/test_cli.py` — argparse wiring: each subcommand maps to
      the right `soarctl_lib` call (patch the lib functions, assert called
      with parsed args); `soarctl` with no args prints help and exits
      non-zero (matches `orchestrator/auth/cli.py` convention)
- [ ] Implement `main()` — subcommands: `package`, `install`, `init`, `up`,
      `down`, `restart`, `status`, `logs`, `migrate --fresh|--upgrade`,
      `users create|deactivate|activate`, `backup create|restore`, `doctor`
- [ ] `chmod +x deploy/soarctl`, shebang `#!/usr/bin/env python3`

## 4. Docs

- [ ] `deploy/prod/README.md` — package (build machine) → transfer bundle
      → install → init → up → migrate --fresh (first boot) → users create
      --admin, mirrors `deploy/stage/README.md`'s structure; explicit
      air-gap note (no network calls past `install`)
- [ ] AGENTS.md: add `deploy/prod/` + `deploy/soarctl*` to the Architecture
      file tree, a `File map` row, and a version-history entry (after
      implementation, not before — per existing AGENTS.md convention)
- [ ] `docs/compose/reports/deploy-cli.md` — written after implementation

## 5. Verification

- [ ] `python -m pytest tests/deploy/ -v`
- [ ] `ruff check deploy/soarctl deploy/soarctl_lib tests/deploy`
- [ ] Manual smoke test against real Docker: `package` → `install` into a
      scratch dir → `init` → `up` → `doctor` → `status` → `migrate --fresh`
      → `users create --admin` → `backup create` → `down`; record the
      outcome in the report (matches project convention of hand-validating
      deploy changes, see spec [S4])
