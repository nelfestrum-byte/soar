# Plan: `soarctl` on-site install (git) + `update`

Spec: [`docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md`](../specs/2026-07-27-soarctl-onsite-update-design.md)

Test-first per module: write the failing test, then implement. Mocks
`deploy.soarctl_lib.<module>.run` the same way existing `tests/deploy/`
tests do — no live Docker/git in the test suite itself (see spec [S5]).

## 1. `bundle.py` — extract shared `build_images()`

- [x] `tests/deploy/test_soarctl_bundle.py` — new test:
      `build_images(repo_root, version)` returns
      `(f"soar-orchestrator:{version}", f"soar-ui:{version}")` and issues the
      two `docker build -f .../Dockerfile.{orchestrator,ui} -t <tag> <repo_root>`
      calls + `docker pull` for each of `BASE_IMAGES` — assert via mocked `run`
- [x] Refactor `package()` to call `build_images()` instead of inlining the
      `docker build`/`docker pull` loop; existing `test_package_builds_and_pulls_and_saves`
      must keep passing unchanged (pure refactor, no behavior change)

## 2. `deploy/prod/config.yaml.template` — real `cors_origins` variable

- [x] Replace the hardcoded `cors_origins: ["https://CHANGE-ME.example.com"]`
      line with `cors_origins: ${CORS_ORIGINS_JSON}`, drop the now-redundant
      comment block above it (the default value in `env.py` carries the same
      placeholder + the README keeps the manual-edit callout)

## 3. `env.py` — `overrides` param + CORS default

- [x] `tests/deploy/test_soarctl_env.py` — new tests:
  - `init_instance(dir)` without `overrides` renders
    `cors_origins: ["https://CHANGE-ME.example.com"]` into `config.yaml`
    (unchanged default, no regression for the air-gap path)
  - `init_instance(dir, overrides={"CORS_ORIGINS_JSON": '["https://soar.example.com"]'})`
    renders that value instead
- [x] Implement: `init_instance(directory, force=False, overrides=None)` —
      add `CORS_ORIGINS_JSON` to the base `values` dict before
      `values.update(overrides or {})`, before rendering

## 4. `prompts.py` — new module

- [x] `tests/deploy/test_soarctl_prompts.py` —
  - `_valid_origin(url)` — table test: `http://x` / `https://x` → `True`;
    `""`, `"x"`, `"ftp://x"` → `False`
  - `prompt_cors_origins(input_fn)` — takes an injected input function
    (not real `input()`) so it's testable: given a fake that first returns an
    invalid value then a valid comma-separated list, returns the parsed,
    validated list and was called twice (re-prompt behavior)
- [x] Implement `_valid_origin()` (pure) and `prompt_cors_origins(input_fn=input)`
      (thin loop calling `input_fn`, default arg keeps production call sites
      simple: `prompt_cors_origins()`)

## 5. `git_source.py` — new module

- [x] `tests/deploy/test_soarctl_git_source.py` —
  - `resolve_version(checkout)` calls `git -C <checkout> describe --tags
    --always --dirty` and returns the stripped stdout (mock `run`)
  - `install(repo, ref, dest_dir)`:
    - given a local path (`Path(repo).exists()`) — does **not** call `git clone`,
      uses the path as the checkout directly
    - given a URL-like string — calls `git clone <repo> <dest_dir>/src`
    - if `ref` given, calls `git -C <checkout> checkout <ref>`
    - calls `build_images()` (imported from `bundle.py`, reused — assert via
      monkeypatching `deploy.soarctl_lib.git_source.build_images`) tagged with
      `resolve_version()`'s result, no `docker save`/`docker load` calls at all
    - copies `docker-compose.yml`/`config.yaml.template` from
      `<checkout>/deploy/prod/` into `dest_dir`, writes `dest_dir/VERSION`
    - writes `dest_dir/source.json` with `{"repo": <original arg>, "checkout":
      <resolved absolute path>}`
  - `update(instance_dir, ref, migrate)`:
    - raises a clear `FileNotFoundError`-style error if `source.json` is
      missing, **before** any `git`/`docker` call (assert zero calls to
      mocked `run`)
    - reads `source.json`, with `ref` given: `git -C <checkout> fetch --tags`
      then `git -C <checkout> checkout <ref>`
    - without `ref`: `git -C <checkout> fetch --tags` then
      `git -C <checkout> pull --ff-only`
    - rebuilds via `build_images()`, calls `env.update_version(instance_dir,
      new_version)` (assert via monkeypatching), calls `compose.up(instance_dir)`
    - `migrate="fresh"` → calls `migrate.stamp_head`; `migrate="upgrade"` →
      calls `migrate.upgrade_head`; `migrate=None` → calls neither
- [x] Implement `resolve_version()`, `install()`, `update()`, using
      `bundle.build_images`, `env.update_version`, `compose.up`,
      `migrate.stamp_head`/`upgrade_head` — no duplicated logic

## 6. `doctor.py` — git-source check

- [x] `tests/deploy/test_soarctl_doctor.py` — new test: when
      `dest_dir/source.json` exists, `run_checks()` includes a `"git
      checkout"` entry; when absent, it doesn't (existing checks list
      unchanged in that case — assert old test still passes)
- [x] Implement `check_git_checkout(instance)`: reads `source.json` if
      present, verifies `git` is on PATH and the recorded checkout path still
      exists; `run_checks()` appends this check only when `source.json` exists

## 7. `cli.py` — wire everything

- [x] `tests/deploy/test_soarctl_cli.py` — new tests:
  - `install --repo <path> --ref <ref> --dir <dir>` dispatches to
    `git_source.install(repo, ref, dest_dir)`, not `bundle.install`
  - `install <bundle> --dir <dir>` (positional, no `--repo`) still dispatches
    to `bundle.install` — no regression
  - `install` with neither a bundle positional nor `--repo` → `SystemExit`
    (via `parser.error`)
  - `install` with **both** a bundle positional and `--repo` → `SystemExit`
  - `init --interactive` dispatches to `prompts.prompt_cors_origins()` and
    passes its result into `env.init_instance(..., overrides={"CORS_ORIGINS_JSON": ...})`
  - `init --cors-origin https://a --cors-origin https://b` passes
    `overrides={"CORS_ORIGINS_JSON": '["https://a", "https://b"]'}` without
    prompting
  - `init --interactive --cors-origin https://a` → `SystemExit` (mutually
    exclusive, per spec [S2])
  - existing `test_init_dispatches_to_env_init_instance` updated for the new
    `overrides=None` default kwarg on the mocked `init_instance` signature
  - `update --ref v1.2.3 --dir <dir>` dispatches to `git_source.update(instance,
    ref="v1.2.3", migrate=None)`
  - `update --migrate fresh --dir <dir>` passes `migrate="fresh"`
- [x] Implement argparse wiring:
  - `install`: `bundle` positional becomes `nargs="?"`; add `--repo`,
    `--ref`; validate exactly one of (`bundle`, `--repo`) via `parser.error()`
    in `main()` (argparse can't express positional-vs-flag mutual exclusion
    natively — same manual-validation precedent as `migrate`'s
    mutually-exclusive group, just not expressible as one)
  - `init`: add `--interactive` (`action="store_true"`), `--cors-origin`
    (`action="append"`); `main()` raises `parser.error()` if both given;
    builds `overrides` dict accordingly and passes to `env.init_instance`
  - new `update` subparser: `--ref` (optional), `--migrate` (`choices=["fresh",
    "upgrade"]`, optional, no default), `--dir`; dispatches to
    `git_source.update(instance, ref=args.ref, migrate=args.migrate)`

## 8. Docs

- [x] `deploy/prod/README.md` — new section "On-site install (this machine
      has internet)" after the existing air-gap walkthrough: `soarctl install
      --repo . --dir soar-prod` → `init --interactive` → `up` → `migrate
      --fresh` → `users create`; separate "Updating an on-site instance"
      subsection: `soarctl update --migrate fresh` (or `--upgrade`), noting
      postgres/redis are not recreated
- [x] AGENTS.md — add `git_source.py`/`prompts.py` to the file map and a
      version-history entry (after implementation, per CLAUDE.md convention)
- [x] `docs/compose/reports/soarctl-onsite-update.md` — written after
      implementation

## 9. Verification

- [x] `python -m pytest tests/deploy/ -v`
- [x] `ruff check deploy/soarctl deploy/soarctl_lib tests/deploy`
- [ ] Manual smoke test against real Docker + git (requires an environment
      with both, not this sandbox): `install --repo .` → `init --interactive`
      → `up` → `migrate --fresh` → `users create` → commit a trivial change →
      `update` → confirm via `docker compose ps` that `soar-postgres`/
      `soar-redis` `CreatedAt` timestamps are unchanged while `soar-orchestrator`/
      `soar-ui` were recreated; record the outcome in the report. **Partial:**
      no Docker daemon was reachable in this sandbox — `git describe` and a
      real `soarctl install --repo .` invocation were verified live up to
      the `docker build` call (see report); full container cycle still
      pending an environment with Docker running.
