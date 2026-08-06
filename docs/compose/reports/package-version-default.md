# Report: `soarctl package` default version + Windows wrapper

Spec: `docs/compose/specs/2026-08-06-package-version-default-design.md`
Plan: `docs/compose/plans/2026-08-06-package-version-default.md`

## Context

Follow-up to `docs/compose/reports/pip-index-mirror.md`. Driving an actual
`docker build` on the dev-lab host (`admsec@192.168.1.78`) with
`PIP_INDEX_URL` pointed at `mirror.yandex.ru` got past the network block
but hit a second, unrelated wall: that mirror's `annotated-doc/` (a new
transitive dependency of recent `fastapi` releases) is an empty
placeholder (`.s3keep` only, no actual package files) — the mirror hasn't
synced it. Confirmed via `curl` against the mirror's simple-index path
directly.

Decision (user): stop iterating on that host's network/mirror situation.
Instead build the deploy bundle on the Windows dev machine, which already
has working internet (VPN), and use the existing air-gapped
package/install flow to ship it to the target. Two gaps blocked doing
that cleanly, both fixed here.

## What changed

- `deploy/soarctl_lib/cli.py`: `package --version` is now optional,
  defaulting to `git_source.resolve_version(repo_root)` — the same
  `git describe --tags --always --dirty` already used by the on-site
  `install`/`update` path, so a version string is never something the
  caller has to invent by hand.
- `soarctl.ps1` (new, repo root): PowerShell counterpart of the bash
  `soarctl` wrapper, for build machines with no POSIX shell. Same
  contract — resolves its own directory, execs `python deploy/soarctl
  @args`, propagates the exit code.
- `tests/deploy/test_soarctl_cli.py`: new test for the version-default
  path (written first, confirmed failing against the old
  `required=True`, passing after).
- `README.md`: added a "Быстрый рецепт" TL;DR block at the top of
  "Деплой — soarctl" (direct feedback: the prior version, inherited from
  the just-deleted `deploy/prod/README.md`, was "непонятно и неудобно"),
  mentioned `soarctl.ps1` next to every `soarctl`/bash-wrapper reference
  in the air-gapped flow, updated `--version` mentions to show it's
  optional. On the target side, keeps `python soarctl ...` (not
  `./soarctl`) — deliberate: the executable bit on a transferred tarball
  extracted on a non-Linux hop (USB/scp from Windows) isn't guaranteed to
  survive, `./soarctl.ps1` doesn't apply there either since the target is
  the air-gapped Linux host, not the Windows build machine.
- `AGENTS.md`: File map entry for `soarctl.ps1` next to the existing
  `soarctl` entry.

## Incidental: Docker Desktop on the build machine

Before the real build could run, Docker Desktop on this Windows machine
wasn't running and then got stuck behind a "lingering processes detected"
dialog on relaunch. Killed the flagged PIDs, then (with explicit
go-ahead) did a full reset — killed all `Docker Desktop`/
`com.docker.backend` processes, `wsl --shutdown` to drop the
`docker-desktop` WSL2 VM entirely, relaunched. Engine came up clean
(29.4.3) a few minutes later. Unrelated to soarctl itself, noted here
because it blocked verifying the actual fix.

## Verification

- `python -m pytest tests/deploy/` — 134 passed (new test + all
  pre-existing).
- `./soarctl.ps1 --help` — dispatches correctly through the wrapper.
- `./soarctl.ps1 package --output <scratchpad>/soar-bundle.tar.gz` — real
  build (not mocked), completed exit 0, 389 MB tarball. Auto-detected
  version `v0.1-180-gb1cf01e-dirty` (the `-dirty` suffix is accurate: this
  session had unrelated uncommitted changes in the working tree from a
  parallel task at build time). Verified contents by extracting (not
  loading, to avoid touching this machine's local Docker state):
  `VERSION`, `docker-compose.yml`, `config.yaml.template`, `soarctl` +
  `soarctl_lib/` all present; `images.tar`'s `manifest.json` lists all
  four expected images
  (`soar-orchestrator:v0.1-180-gb1cf01e-dirty`,
  `soar-ui:v0.1-180-gb1cf01e-dirty`, `redis:7-alpine`,
  `postgres:16-alpine`).
