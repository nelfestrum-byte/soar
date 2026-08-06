# Plan: GitManager empty initial commit

Spec: `docs/compose/specs/2026-08-06-git-manager-empty-initial-commit-design.md`

- [x] `tests/orchestrator/test_git_manager.py`: add
      `test_git_manager_ensure_repo_on_empty_dir` — new fixture (`tmp_path`
      dir with nothing in it, no `test.txt`), call `ensure_repo()`, assert
      it doesn't raise and `.git` exists.
- [x] Run it, confirm it fails against current code (`RuntimeError: git
      commit failed:` — same empty-stderr symptom seen live).
- [x] `orchestrator/core/git_manager.py::ensure_repo()`: add
      `--allow-empty` to the initial commit call.
- [x] Run `tests/orchestrator/test_git_manager.py`, confirm all pass (11
      passed).
- [x] Report: `docs/compose/reports/git-manager-empty-initial-commit.md`.
