# Plan: `soarctl package` default version + Windows wrapper

Spec: `docs/compose/specs/2026-08-06-package-version-default-design.md`

- [x] `tests/deploy/test_soarctl_cli.py`: add
      `test_package_defaults_version_from_git_describe` — monkeypatch
      `cli.git_source.resolve_version` to return a known string, call
      `cli.main(["package", "--output", ...])` (no `--version`), assert
      `bundle.package` received that version.
- [x] `tests/deploy/test_soarctl_cli.py`: existing
      `test_package_dispatches_to_bundle_package` keeps passing unchanged
      (explicit `--version` still wins, no `git_source` call needed for
      that path — assert via monkeypatch not being called, or just that
      the explicit value flows through).
- [x] Run new test, confirm it fails against current `cli.py`.
- [x] `cli.py`: `pkg.add_argument("--version", default=None, ...)`; in
      `main()`, `version = args.version or git_source.resolve_version(paths.repo_root(Path(__file__)))`
      before calling `bundle.package`.
- [x] Run `tests/deploy/`, confirm green (134 passed).
- [x] `soarctl.ps1` at repo root: thin wrapper, `python
      "$scriptDir/deploy/soarctl" @args`, `exit $LASTEXITCODE`.
- [x] Manually verify: `./soarctl.ps1 --help` resolves and dispatches
      correctly. `./soarctl.ps1 package --output ...` (real build, not
      mocked) kicked off after fixing Docker Desktop on this machine
      (lingering processes from a previous session required a manual
      restart + WSL reset first) — see report for the outcome.
- [x] `README.md`: mention `soarctl.ps1` alongside the bash wrapper under
      "Деплой — soarctl"; note `--version` is now optional. Also added a
      "Быстрый рецепт" TL;DR block at the top of the section per direct
      user feedback that the previous version was "непонятно и неудобно".
- [x] Report: `docs/compose/reports/package-version-default.md`.
