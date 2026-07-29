---
feature: soarctl-inplace-onsite
date: 2026-07-29
spec: docs/compose/specs/2026-07-29-soarctl-inplace-onsite-design.md
plan: docs/compose/plans/2026-07-29-soarctl-inplace-onsite.md
---

# Report: `soarctl` in-place on-site instances

## What was built

Reworked the on-site half of `soarctl` (git-checkout-based install/update,
`deploy/prod/`) so the checkout itself is the instance — no separate
`--dir`-named directory, no `--repo <url>` cloning. The air-gapped bundle
path (`package`/`install <bundle.tar.gz>`) is untouched.

- **`deploy/soarctl_lib/paths.py`** — `instance_dir()` rewritten to
  auto-discover the working directory the way `git` finds its repo root:
  `--dir` wins if passed; otherwise walk up from cwd for a directory
  containing `docker-compose.yml` directly (bundle instances, from any
  subdirectory); otherwise walk up for `pyproject.toml` and resolve to
  `<root>/deploy/prod` if it has a `docker-compose.yml` (on-site instances,
  from any subdirectory of the checkout); otherwise falls back to cwd
  (previous behavior, unchanged for the pre-`init` bundle case).
- **`deploy/soarctl_lib/git_source.py`** — `install(checkout, ref)` no
  longer takes `repo: str`/`dest_dir: Path`. No more `git clone` branch, no
  more copying `docker-compose.yml`/`config.yaml.template` — those already
  live at `<checkout>/deploy/prod/`, tracked in git; `install` only runs
  `git checkout <ref>` (if given), builds images, and writes
  `VERSION`/`source.json` into that same directory. `source.json` dropped
  the now-meaningless `repo` key, keeping only `checkout`. `update()` is
  unchanged (still reads `checkout` from `source.json`).
- **`deploy/soarctl_lib/cli.py`** — `install`: `bundle` and `--repo` are
  simply an if/else now, not a required mutually-exclusive pair — if
  neither is given, it resolves the checkout via `paths.repo_root(Path.cwd())`
  (a clean `parser.error()` if that fails, i.e. not inside a checkout).
  `--repo` no longer accepts URLs, just an optional local-path override.
- **`deploy/soarctl_lib/doctor.py`** — no code change needed;
  `check_git_checkout()` only ever read the `checkout` key from
  `source.json`, already compatible with the simplified shape.
- **`soarctl`** (new, repo root) — bash wrapper (`exec python3
  deploy/soarctl "$@"`), executable bit set via `git update-index
  --chmod=+x`, `.gitattributes` pins it to LF so a Windows checkout doesn't
  break the shebang on the Linux deploy target. Drops the
  `python deploy/soarctl` prefix: `git clone <url> soar && cd soar &&
  ./soarctl install && ./soarctl init && ./soarctl up`.
- Docs: `deploy/prod/README.md`, root `README.md`, `AGENTS.md`,
  `CHANGELOG.md` (v0.16) rewritten for the new on-site flow;
  `deploy/.gitignore` gained `prod/VERSION`/`prod/source.json` (join the
  existing `prod/config.yaml`/`prod/.env` entries, since these now land
  directly inside the tracked `deploy/prod/` directory);
  `2026-07-27-soarctl-onsite-update-design.md` marked superseded (pointer
  at the top, referenced from `CLAUDE.md`'s spec list) rather than deleted,
  same precedent as `2026-07-03-bugfixes-design.md`.

## Bug found in the process

The on-site flow this replaces was never actually usable as documented:
`git_source.install()` copied `docker-compose.yml`/`config.yaml.template`/
`VERSION`/`source.json` into the `--dir` target but never `soarctl`/
`soarctl_lib` itself (unlike the bundle path, which does bundle them) — the
README's own `cd soar-prod && python soarctl doctor` step would have failed
with "can't open file 'soarctl'". This was never caught because the prior
feature's manual verification stopped at the `docker build` call, before
reaching that step. Root cause was structural (two disconnected
directories), not a one-line fix, hence this rework rather than a patch.

## Tests

Test-first per the plan — each new/changed test confirmed failing for the
right reason before implementing (see commands below).

- `tests/deploy/test_soarctl_paths.py` — 8 new tests for `instance_dir()`
  auto-discovery (explicit `--dir` wins; bundle marker from its own root
  and from a nested subdirectory; checkout marker from repo root and from a
  nested subdirectory; fallback to cwd with no markers, and with a repo
  root that has no `deploy/prod`).
- `tests/deploy/test_soarctl_git_source.py` — rewritten: removed the
  URL-clone test (feature removed); added tests for in-place `VERSION`/
  `source.json` writes, that `install()` doesn't touch the already-present
  `docker-compose.yml`/`config.yaml.template`, `--ref` checkout ordering,
  and `build_images()` tagging — `update()` tests otherwise unchanged.
- `tests/deploy/test_soarctl_cli.py` — `install --repo` test updated to the
  new 2-arg signature; new tests for auto-discovery-from-cwd and the
  not-in-a-checkout error path; `bundle`+`--repo` conflict test kept.

```
python -m pytest tests/deploy/ -q
# 115 passed (was 106 before this change)
ruff check deploy/soarctl deploy/soarctl_lib tests/deploy
# All checks passed!
```

## Manual verification

Docker was available in this session (unlike the prior on-site-update
report's first pass), so this went further than a dry run:

- Built a real scratch git checkout (`git init`, real `deploy/prod/*` files
  copied from this repo, real `pyproject.toml`, tagged `v9.9.9`).
- `python deploy/soarctl install` (real subprocess, no mocks) run from the
  checkout root: real `git describe` resolved `v9.9.9`; real `docker build`
  was invoked with the correct `-f <checkout>/deploy/prod/Dockerfile.orchestrator
  -t soar-orchestrator:v9.9.9 <checkout>` arguments — it failed only because
  the scratch checkout intentionally omitted `soar/`/`alembic/`/`alembic.ini`
  (not a real source tree), confirming the path-resolution and dispatch
  logic end-to-end, short of a full build.
- `python deploy/soarctl doctor` run from `<checkout>/orchestrator/api/` (a
  synthetic nested subdirectory, no `--dir` passed): correctly reported
  `<checkout>/deploy/prod/.env missing` — proof that `instance_dir()`
  walked up from a subdirectory, found `pyproject.toml` at the checkout
  root, and resolved to `<root>/deploy/prod`, exactly the auto-discovery
  this feature exists to deliver. This is the concrete fix for the
  "must be in the exact directory" complaint that started this work.
- `bash -n soarctl` — syntax-checked clean. `./soarctl --help` could not be
  exercised directly in this Windows sandbox: `python3` on this machine
  resolves to a Microsoft Store "app execution alias" stub that prints
  `Python` and exits instead of running anything (a Windows-only artifact —
  irrelevant on the Linux deploy targets this wrapper is for, where
  `python3` is a real interpreter). Confirmed instead via
  `python deploy/soarctl --help` (the wrapper's target) and a blob-level
  check (`git cat-file -p`) that the committed file is LF, mode `100755`.
- Not exercised: a full `install → init → up → migrate --fresh → users
  create → update` cycle against the real repo's full source tree — would
  require either a disposable full clone or dirtying this repo's own
  `deploy/prod/` with instance files, neither of which seemed warranted for
  a directory-resolution/CLI-wiring change already covered by the checkout
  above plus 115 unit tests. Flagged as a follow-up if a reviewer wants a
  full live cycle before this reaches a real deploy target.

## Known follow-ups

- Full live `install → init → up → migrate → users create → update` cycle
  on a genuine full clone, on Linux — not done here (see above).
- Windows-native wrapper (`.cmd`/`.ps1`) — explicitly out of scope (spec
  [S3]); the deploy target is a Linux/Docker machine, not this repo's own
  dev environment.
