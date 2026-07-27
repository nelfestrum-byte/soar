---
feature: soarctl-onsite-update
date: 2026-07-27
spec: docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md
plan: docs/compose/plans/2026-07-27-soarctl-onsite-update.md
---

# Report: `soarctl` on-site install (git) + `update`

## What was built

A second `soarctl install` source, and a new `soarctl update` command, for
deploying `deploy/prod/` on a machine that has internet access itself —
alongside (not replacing) the existing air-gap bundle path from
`docs/compose/specs/2026-07-22-deploy-cli-design.md`.

- **`deploy/soarctl_lib/bundle.py`** — extracted `build_images(repo_root,
  version) -> (orchestrator_tag, ui_tag)` out of `package()`: builds/tags
  the two images and pulls the base images, with no `docker save` involved.
  `package()` now calls it instead of inlining the same steps — pure
  refactor, its existing tests pass unchanged.
- **`deploy/soarctl_lib/git_source.py`** (new) — `resolve_version(checkout)`
  (`git describe --tags --always --dirty`), `install(repo, ref, dest_dir)`
  (local path used as-is / URL cloned into `<dest>/src`, checks out `ref` if
  given, builds images via `build_images()`, copies
  `docker-compose.yml`/`config.yaml.template` into the instance dir, writes
  `VERSION` and a new `source.json` marker), and `update(instance, ref,
  migrate)` (reads `source.json`, `git fetch --tags` + `checkout <ref>` or
  `pull --ff-only`, rebuilds, `env.update_version()`, `compose.up()`, then
  `migrate.stamp_head`/`upgrade_head` only if `--migrate` was given).
- **`deploy/soarctl_lib/prompts.py`** (new) — `_valid_origin()` (pure
  `http(s)://` check) + `prompt_cors_origins(input_fn=input)` (re-prompt
  loop), used by `soarctl init --interactive`.
- **`deploy/soarctl_lib/env.py`** — `init_instance()` gained `overrides:
  dict[str, str] | None`. `CORS_ORIGINS_JSON` is now a template-only value
  (never written to `.env`, unlike the actual secrets) with the same
  placeholder default as before; `overrides` lets `--interactive`/
  `--cors-origin` supply a real one.
- **`deploy/prod/config.yaml.template`** — `cors_origins` changed from a
  hardcoded placeholder string to `${CORS_ORIGINS_JSON}`, a real template
  variable. Plain `soarctl init` (no flags) still renders the identical
  placeholder text as before — no behavior change for the air-gap path.
- **`deploy/soarctl_lib/doctor.py`** — `check_git_checkout()`: returns
  `None` (no-op) when the instance has no `source.json`, otherwise verifies
  `git` is on PATH and the recorded checkout still exists. `run_checks()`
  only appends it when relevant.
- **`deploy/soarctl_lib/cli.py`** — `install`'s `bundle` positional is now
  optional; added `--repo`/`--ref` (exactly one of `bundle`/`--repo`
  required, enforced via `parser.error()`, same manual-validation precedent
  as `migrate`'s mutually-exclusive group). `init` gained `--interactive`/
  `--cors-origin` (mutually exclusive). New `update` subcommand: `--ref`,
  `--migrate {fresh,upgrade}` (no default — matches the existing
  no-auto-detect philosophy of `soarctl migrate`).
- **`deploy/prod/README.md`** — new "On-site install" + "Updating an
  on-site instance" sections after the existing air-gap walkthrough;
  air-gap instructions untouched.

`deploy/stage/` was not touched — it already has its own `build:`-based
workflow for the same "on-site, has internet" idea at QA-stand scale.

## Design decisions worth flagging

- **"No teardown of containers/DB" is structural, not a new flag.**
  `update()` never calls `compose down`, and `postgres`/`redis` in
  `docker-compose.yml` reference fixed image tags that `update` never
  changes — `docker compose up -d` therefore only recreates `orchestrator`/
  `ui` on its own, standard compose behavior. No new "safe restart" mode was
  needed.
- **`update` only works for git-sourced instances.** Bundle-installed
  instances have no checkout on the target machine (that's the point of
  air-gap) and keep using the documented `install <new-bundle>` flow —
  `_read_source()` raises a clear error, before any `git`/`docker` call, if
  `source.json` is missing.
- **CORS placeholder behavior is unchanged unless you opt in.** `--cors-
  origin`/`--interactive` are both new, additive flags; the default `soarctl
  init` output is byte-for-byte the same placeholder as before this change.

## Tests

36 new tests across
`tests/deploy/test_soarctl_{bundle,env,prompts,git_source,doctor,cli}.py`
(one new `test_soarctl_prompts.py`, one new `test_soarctl_git_source.py`,
the rest added to existing files), test-first per the plan — each new test
was run and confirmed failing (`ImportError`/`AttributeError`/missing
function) before implementing.

```
python -m pytest tests/deploy/ -q
# 106 passed
ruff check deploy/soarctl deploy/soarctl_lib tests/deploy
# All checks passed!
```

Full repo suite (`python -m pytest tests/ -q`): 683 passed, 1 skipped, 4
failed — all four pre-existing and unrelated to this change (three
`test_redis_integration.py` tests need a live Redis server; one
`test_openapi.py::test_generate_config` failure predates this branch).

**Update after Docker became available in this environment** (see
"Update" below): re-ran the full suite against live Redis — 686 passed,
1 skipped, 1 failed (only the pre-existing `test_openapi.py` failure
remains; the three Redis-integration tests now pass instead of skipping).

## Manual verification

No Docker daemon was running in this sandbox initially (`docker ps` failed
to reach `dockerDesktopLinuxEngine`), so the full build+up+migrate+update
cycle against live containers was **not** exercised in the first pass —
see "Update" below for what changed once Docker was started.

What *was* verified live in the first pass, against the real repo (no
mocks):

- `git describe --tags --always --dirty` in this checkout returns
  `v0.1-121-g94555df-dirty` — confirms the version-resolution command and
  its `-dirty` suffix behavior work as designed against a real git history
  with tags.
- `python deploy/soarctl install --repo . --dir <scratch>` (real subprocess,
  real CLI entrypoint, no mocks) correctly: detected `.` as an existing
  local path (no `git clone` attempted), resolved the same version string
  as the standalone `git describe` above, and reached the `docker build`
  call before failing — the failure was exactly "Docker daemon not
  reachable", not an import error, argument-parsing error, or logic bug.
  This confirms the CLI wiring, argparse changes, and `git_source.install()`
  path all work end-to-end short of the Docker daemon itself. Scratch
  directory removed afterward.

## Update: Docker became available — `deploy/stage` rebuild + real bug found

Once Docker was started, the user asked to rebuild the (already-running but
3-weeks-stale) `deploy/stage` stand and re-run the full suite. Rebuilding it
(`cd deploy/stage && make build`) surfaced a real, unrelated deployment bug
introduced by v0.12/P12, independent of this feature:

- `soar/tools/http_client.py` does `import httpx` unconditionally, and
  `soar/tools/__init__.py` imports `HttpClient` at module load time — that
  chain is reached from `orchestrator/api/connectors.py` (`from
  soar.tools.openapi import OpenAPIGenerator` → `soar.tools.__init__` →
  `http_client`), so the orchestrator process cannot start without `httpx`
  installed. `httpx` was added to `soar/requirements.txt` for P12, but both
  `deploy/stage/Dockerfile.orchestrator` and `deploy/prod/Dockerfile.orchestrator`
  only install `orchestrator/requirements.txt` plus a hand-picked extra list
  (`elasticsearch vt-py requests`) that was never updated to include it —
  any orchestrator image built from current `main` fails at import with
  `ModuleNotFoundError: No module named 'httpx'`. This is exactly why the
  stage containers had been running unrebuilt for 3 weeks (`docker ps`
  showed no `postgres` container at all, meaning stage's orchestrator was
  still on a pre-P14 image that never needed Postgres either).
- Fix: added `httpx` to the `pip install` line in both Dockerfiles
  (one-line, minimal — not a design change, so no separate spec was written
  for it; logged in `CHANGELOG.md`'s v0.13 entry instead).
- Verified live end-to-end after the fix: `make build` → all four
  containers (`redis`, `postgres`, `orchestrator`, `ui`) `healthy` →
  `psql \dt` on the fresh Postgres showed `create_all()` had produced
  `stage_{api_keys,audit_log,refresh_tokens,users,workflow_jobs}` → `make
  migrate-stamp-initial` (correct choice per the existing fresh-DB
  convention — this was Postgres's first-ever boot for this stack, no
  `stage_postgres-data` volume existed before) → `alembic heads` confirmed
  `42fbd47b0d46 (head)`, matching the stamp → `GET /health` → `{"status":
  "ok"}`.
- Noted but **not** fixed (pre-existing, already self-documented, out of
  scope here): the `42fbd47b0d46` migration's partial index
  (`ix_workflow_jobs_pending_triggered_at`) uses the literal table name
  `workflow_jobs`, not the `stage_`-prefixed one, and — separately —
  `stamp head` never executes any migration's `upgrade()` DDL at all. On
  this fresh install neither path created the index (`\d
  stage_workflow_jobs` shows no partial index). This is a latent gap
  wherever a migration adds something `create_all()` doesn't know about
  (an index not mirrored in the SQLAlchemy model) combined with the
  documented stamp-on-fresh-install convention — a correctness non-issue
  (the SQL queue's claim query still works, just without the intended
  index-assisted speedup), flagged here for whoever picks up
  `table_prefix` handling in migrations (already tracked as Known
  Limitations #8's neighborhood) rather than fixed inline.
- Also confirmed: `stage_users` is empty on this fresh Postgres (auth
  enabled via `auth.secret_key` in `deploy/stage/config.yaml`, but no admin
  bootstrapped yet) — `GET /status` correctly returned `401 Not
  authenticated`. Bootstrapping the first admin
  (`docker compose exec orchestrator python -m orchestrator.auth.cli
  create-user --username ... --role admin`) was left for the user to do
  interactively (password prompt), not done here.
- Full suite re-run with live Redis (see Tests section above): 686 passed,
  1 skipped, 1 pre-existing failure.

The on-site `soarctl install --repo`/`update` feature itself (this report's
main subject, targeting `deploy/prod/`, a separate profile from
`deploy/stage/`) was not re-exercised against live containers in this pass
— that would mean standing up a *new* scratch `deploy/prod` instance, which
wasn't what was asked for here (the ask was specifically to update the
already-running stage stand). It remains the one open item below.

## Known follow-ups (not blocking, not in scope here)

- Full live smoke test of `soarctl install --repo` + `update` against
  `deploy/prod/` (`install --repo .` → `init --interactive` → `up` →
  `migrate --fresh` → `users create` → commit a change → `update` →
  confirm via `docker compose ps` that `postgres`/`redis` `CreatedAt`
  timestamps are unchanged) — Docker is now available in this environment,
  so this can be run; it just wasn't part of the stage-update ask that
  prompted this session's Docker-available follow-up.
- No automated rollback command — reverting `SOAR_VERSION` in `.env` to a
  still-present older image tag and re-running `soarctl up` remains a
  manual step, by design (see spec non-goals).
- Multi-instance support remains out of scope — AGENTS.md Known
  Limitations #8, unchanged by this work.
