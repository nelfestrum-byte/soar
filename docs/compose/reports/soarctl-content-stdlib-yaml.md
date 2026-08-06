# Report: `soarctl` host-stdlib-only fix + missing base-pack fallback

Spec: `docs/compose/specs/2026-08-06-soarctl-content-stdlib-yaml-design.md`
Plan: `docs/compose/plans/2026-08-06-soarctl-content-stdlib-yaml.md`

Triggered by a real prod incident: `./soarctl --help` crashed with
`ModuleNotFoundError: No module named 'yaml'` on a fresh on-site host, and
after a manual `pip install pyyaml` workaround, `./soarctl install` hit a
second, unrelated failure building the orchestrator image.

## What changed

**`deploy/soarctl_lib/content.py`** — removed the module's only non-stdlib
import (`yaml`). Added `_yaml_load`/`_yaml_dump`, which shell out to
`docker compose exec -T orchestrator python3 -c ...` (pyyaml already lives
in that container's image, per `orchestrator/requirements.txt`) and
exchange data with the host as JSON — the same "proxy into the running
container instead of duplicating its dependencies" pattern `users.py`
already uses for `orchestrator.auth.cli`. `install`, `list_installed`,
`remove`, `_read_current_state`, `_read_manifest` now take an `instance:
Path` argument (previously content commands were the only subcommand group
with no `--dir`/instance concept at all — now consistent with
`backup`/`users`/`migrate`).

**`deploy/soarctl_lib/cli.py`** — wired `--dir` onto `content install/list/remove`,
resolves `paths.instance_dir(args)` once and passes it through.

**`deploy/soarctl_lib/bundle.py::build_images`** — falls back to an empty
temp directory for the `basepack` Docker build context when
`<repo_root>/../soar-content-pack` doesn't exist, instead of failing the
build. `orchestrator/main.py::seed_connector_pack` already treats a missing
`manifest.yaml` as "skip seeding" — this was already a supported runtime
state, just not a supported *build-time* one until now.

## Verified

- Import audit (`grep '^import \|^from '` across every `deploy/soarctl_lib/*.py`):
  zero non-stdlib imports remain.
- `tests/deploy/` — 131/131 pass, including 2 new `test_soarctl_bundle.py`
  cases (fallback-to-empty-dir, uses-sibling-when-present) and the
  `test_content_cli.py`/`test_soarctl_cli.py` updates for the new `instance`
  parameter.
- Full suite (`tests/`): 814 passed, 9 skipped, 3 pre-existing failures in
  `tests/orchestrator/test_redis_integration.py` — unrelated, need a live
  local Redis (`ConnectionError`/DNS on `localhost:6379`), not touched by
  this change.

## Judgment calls

- `content install/list/remove` now require the target instance's
  orchestrator container to be running (`docker compose exec` needs a live
  container) — stricter than before (`docker run alpine` only needed the
  volume to exist), but matches the existing precondition on `backup`/`users`,
  and installing content into an instance that isn't up was never a
  documented supported flow.
- Did not attempt to give `soar-content-pack` a real distribution mechanism
  (git remote, bundling into the release tarball, etc.) — that's a bigger,
  separate decision (the repo is deliberately local-only per `AGENTS.md`
  today) and out of scope for this incident fix. The empty-fallback change
  only makes "no content pack" a working, no-crash configuration; teams that
  want built-in connectors still need to get `soar-content-pack` onto the
  build host themselves.
