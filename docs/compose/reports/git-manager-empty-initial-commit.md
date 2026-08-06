# Report: GitManager `ensure_repo()` fails on a genuinely empty content dir

Spec: `docs/compose/specs/2026-08-06-git-manager-empty-initial-commit-design.md`
Plan: `docs/compose/plans/2026-08-06-git-manager-empty-initial-commit.md`

## Found live, on the lab host

`soarctl up` failed on a fresh air-gapped install (bundle built without
the sibling `soar-content-pack` checkout, so `connectors_dir`/
`workflows_dir`/`actions_dir` were genuinely empty on first boot):
`soar-orchestrator` crashed with `RuntimeError: git commit failed:`
(empty message — git's "nothing to commit" goes to stdout, not stderr).
`docker-compose.yml`'s `restart: unless-stopped` restarted the
container; the second attempt's `ensure_repo()` saw `.git` already
present (created by the first attempt's `git init`, before its `commit`
failed) and skipped the whole init block, so the instance recovered on
its own within ~90s — but `soarctl up`'s own healthcheck-wait aborted
with a nonzero exit and a scary traceback before that recovery
completed, and `soar-ui` was left in `Created` (never started, since its
compose dependency chain aborted with the rest). Fixed live by manually
re-running `python3 soarctl up`, which just started the already-created
`soar-ui`.

A related bug in the same file (`commit()` misinterpreting "nothing to
commit" as an error) was already fixed 2026-07-27
(`docs/compose/reports/git-manager-nothing-to-commit.md`) — that fix
didn't reach `ensure_repo()`'s own initial-commit call, which is what
actually crashed here.

## What changed

`orchestrator/core/git_manager.py::ensure_repo()`: the initial commit
now passes `--allow-empty`. An empty initial commit is the standard git
pattern for "establish the repo root with nothing in it yet" — exactly
this case. `commit()` itself untouched (already correct).

## Verification

- `tests/orchestrator/test_git_manager.py`: new
  `test_git_manager_ensure_repo_on_empty_dir` (empty `tmp_path` dir, no
  seed file) — confirmed failing against the pre-fix code with the same
  `RuntimeError: git commit failed:` seen live, passing after the
  one-line fix. Full file: 11/11 passed.
- `python -m pytest tests/orchestrator` — 575 passed, 9 skipped, 3 failed
  (`test_redis_integration.py` — needs a live Redis server, unrelated,
  same 3 pre-existing failures noted in the 2026-07-27 report). No new
  failures.

## Not done as part of this fix

Not re-deployed to the lab host — the running instance there already
self-healed past this specific crash (see above) and is up; this fix
prevents the crash-and-recover cycle on the *next* fresh install/reboot
rather than something that needs re-applying to already-running
containers.
