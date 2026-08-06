# `soarctl package`: default `--version`; Windows build wrapper

## [S1] Problem

Follow-up from the `PIP_INDEX_URL` work (`docs/compose/specs/2026-08-06-pip-index-mirror-design.md`):
that dev-lab host's network can't reach `pypi.org` reliably, and the
available mirror (`mirror.yandex.ru`) doesn't have every current transitive
dependency synced (`annotated-doc`, pulled in by recent `fastapi`
releases) — confirmed by driving an actual `docker build` on the host.
Decision: stop fighting that specific host's network, build the bundle on
a machine that already has working internet (the Windows dev machine,
VPN'd), transfer it, `soarctl install` on the air-gapped target instead.

Two frictions surfaced building that bundle:

1. `soarctl package --version X.Y.Z` requires `--version` explicitly —
   every other soarctl path that needs a version
   (`git_source.py::resolve_version`, used by on-site `install`/`update`)
   already derives it from `git describe --tags --always --dirty`. No
   reason `package` should make the caller type it by hand.
2. The repo-root wrapper (`./soarctl`) is a bash script — unusable as
   `./soarctl` on the Windows build machine (no bash on `PATH` outside Git
   Bash, and even there `set -euo pipefail` + `exec` assumes a POSIX
   shell). `python deploy/soarctl ...` still works, but that's exactly the
   prefix the wrapper exists to avoid (see its own docstring / the on-site
   spec).

## [S2] Solution

- `cli.py`: `--version` on `package` becomes optional. When omitted,
  resolve it via `git_source.resolve_version(repo_root)` — same function
  already used by the on-site path, so a bundle built from a given commit
  and an on-site instance built from the same commit get the same version
  string (including the `-dirty` suffix convention).
- New `soarctl.ps1` at repo root, mirroring `soarctl` (bash): resolves its
  own directory, execs `python deploy/soarctl @args`, propagates the exit
  code. `python`, not `python3` — that's what's on `PATH` on Windows.

## [S3] Non-goals

- `--output` stays required — no complaint raised about it, and unlike
  version there's no existing convention elsewhere in soarctl to default
  it from.
- Not touching the Yandex-mirror completeness gap itself — out of scope,
  see the pip-index-mirror spec's own out-of-scope note; this spec is
  about removing friction from the alternative (build on a machine that
  already has working internet), not about fixing that mirror.
