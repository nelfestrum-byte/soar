---
feature: soarctl-inplace-onsite
date: 2026-07-29
spec: docs/compose/specs/2026-07-29-soarctl-inplace-onsite-design.md
---

# Plan: `soarctl` in-place on-site instances

Test-first throughout: write the failing test, run it, confirm the failure
reason, then implement.

## 1. `paths.instance_dir()` auto-discovery

- [ ] Test: `--dir` explicit still wins even when cwd would otherwise
      auto-discover something else
- [ ] Test: cwd itself has `docker-compose.yml` → returned as-is (bundle
      case, unchanged behavior for existing bundle tests)
- [ ] Test: cwd nested two levels under a directory with
      `docker-compose.yml` → walks up and finds it (new: bundle instance,
      invoked from a subdirectory)
- [ ] Test: cwd is repo root (has `pyproject.toml`, has
      `deploy/prod/docker-compose.yml`) → resolves to `deploy/prod`
- [ ] Test: cwd is nested under repo root (e.g. `orchestrator/api/`) →
      still resolves to `<repo_root>/deploy/prod`
- [ ] Test: neither marker found anywhere up the tree → falls back to cwd,
      resolved (existing `test_instance_dir_defaults_to_cwd` must keep
      passing unchanged)
- [ ] Implement `instance_dir()` per [S2] resolution order in the spec
- [ ] Run `pytest tests/deploy/test_soarctl_paths.py -q`

## 2. `git_source.install()` in place, URL clone removed

- [ ] Update fixture helper to pre-place `docker-compose.yml` inside
      `<checkout>/deploy/prod/` (already true) and assert `install()` does
      **not** touch/recopy it (same file, same mtime, or just assert
      content unchanged if mtime isn't practical to assert)
- [ ] Test: `install(checkout, ref=None)` writes `VERSION` +
      `source.json` (`{"checkout": str(checkout.resolve())}`) into
      `checkout/deploy/prod/`, returns that path
- [ ] Test: `install(checkout, ref="v2.0.0")` runs
      `git -C <checkout> checkout v2.0.0` before resolving version
- [ ] Test: `install()` calls `build_images(checkout, version)` — no
      `docker save`/`docker load`
- [ ] Remove `test_install_from_url_clones_into_dest_src` (feature gone)
      and the `dest_dir`-copies-`docker-compose.yml`/`config.yaml.template`
      assertions from the local-path test (nothing to copy anymore)
- [ ] Implement `install(checkout: Path, ref: str | None) -> Path` per spec
      (drop `repo: str`/URL branch, drop `dest_dir` param, drop
      `_populate_instance_files`'s copy calls — keep only the
      `VERSION`/`source.json` writes)
- [ ] `update()` — no behavior change needed (`_read_source` already reads
      `checkout` from `source.json`); just confirm existing tests still
      pass against the simplified `source.json` shape (drop the `repo` key
      assertions)
- [ ] Run `pytest tests/deploy/test_soarctl_git_source.py -q`

## 3. `cli.py` argparse

- [ ] Test (`test_soarctl_cli.py`): `install` parser no longer accepts a
      bare URL-implying flow — `--repo` now takes a local path only
      (no code-level validation needed, just confirm the clone call is
      gone by asserting `git_source.install` is invoked with 2 args, not 3)
- [ ] Test: `install` with neither `bundle` nor `--repo` given resolves
      `--repo` to the auto-discovered checkout (via `paths.instance_dir`'s
      sibling logic — reuse `repo_root()` walk-up), i.e. bare
      `soarctl install` works from inside a checkout with zero flags
- [ ] Implement: `install.add_argument("--repo", default=None, help="Local checkout path (default: auto-discovered from cwd)")`;
      in `main()`, when neither `bundle` nor `--repo`, resolve checkout via
      `paths.repo_root(Path.cwd())` instead of erroring
      (`bundle`/`--repo` mutual-exclusivity check only fires when
      `--repo` AND `bundle` are both given, not when both are absent)
- [ ] Run `pytest tests/deploy/test_soarctl_cli.py -q`

## 4. `doctor.py`

- [ ] Confirm `check_git_checkout()` still works unchanged against the
      simplified `source.json` (`checkout` key only) — likely no code
      change, just re-run its existing tests
- [ ] Run `pytest tests/deploy/test_soarctl_doctor.py -q`

## 5. Root-level `./soarctl` wrapper

- [ ] Write `soarctl` at repo root (bash, per [S2])
- [ ] Set executable bit (`git update-index --chmod=+x soarctl` after
      staging, or `chmod +x` — verify with `git ls-files -s soarctl` shows
      mode `100755`)
- [ ] Manual check: `./soarctl --help` from repo root prints the same help
      as `python deploy/soarctl --help`

## 6. Docs

- [ ] `deploy/prod/README.md` — rewrite "On-site install" +
      "Updating an on-site instance" sections per [S5] (single directory,
      `./soarctl`, no `--dir`)
- [ ] `deploy/.gitignore` — add `prod/VERSION`, `prod/source.json` (join
      the existing `prod/config.yaml`/`prod/.env` entries — these are now
      written directly into the tracked `deploy/prod/` directory instead of
      a separate untracked instance dir, so they need explicit ignores to
      avoid showing up as untracked/dirty in the checkout `git status`)
- [ ] AGENTS.md — update the `soarctl`/deploy references (line ~71-74,
      ~506-518) to describe the in-place on-site model; note the version
      entry per existing changelog convention (after implementation, not
      before, per CLAUDE.md)
- [ ] `CHANGELOG.md` — new entry

## 7. Full verification

- [ ] `python -m pytest tests/deploy/ -q`
- [ ] `ruff check deploy/soarctl deploy/soarctl_lib tests/deploy soarctl`
- [ ] Manual e2e per spec [S4] if Docker is available in this environment;
      otherwise document what was/wasn't exercised, same precedent as the
      prior on-site-update report
- [ ] Write `docs/compose/reports/soarctl-inplace-onsite.md`
