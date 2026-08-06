# GitManager: `ensure_repo()` fails on a genuinely empty content dir

## [S1] Problem

Reproduced live on a fresh air-gapped `soarctl install` (bundle built
without the sibling `soar-content-pack` checkout, so the image shipped
with zero built-in connectors — `connectors_dir`/`workflows_dir`/
`actions_dir` are genuinely empty on first boot):

```
RuntimeError: git commit failed:
ERROR:    Application startup failed. Exiting.
```

`GitManager.ensure_repo()` (`orchestrator/core/git_manager.py:42-51`)
does `git init && git add . && git commit -m "Initial commit"`
unconditionally. On an empty directory, `git add .` stages nothing, and
`git commit` without `--allow-empty` exits non-zero with "nothing to
commit" — printed to git's **stdout**, not stderr, so `_run()`'s
`RuntimeError(f"git {args[0]} failed: {stderr.decode()}")` renders with
an empty message, making the crash harder to diagnose than it needs to
be on top of crashing at all.

The container crash-loops once, then self-heals: `docker-compose.yml`
sets `restart: unless-stopped` on every service, so Docker restarts it;
on the second attempt `ensure_repo()`'s `if not os.path.exists(git_dir)`
guard is now `False` (`git init` from the first attempt already created
`.git`, even though the following `commit` failed), so the whole
init/add/commit block is skipped and startup proceeds normally. Net
effect: a confusing crash-and-recover on every fresh instance with no
seeded content, and `soarctl up`'s own healthcheck-wait aborts with a
nonzero exit + traceback before the self-heal completes, even though the
system is fine moments later.

A related bug (`commit()` misinterpreting "nothing to commit" as an
error) was already fixed 2026-07-27
(`docs/compose/specs/2026-07-27-git-manager-nothing-to-commit-design.md`)
— that fix touched `commit()` only (per-file commits after the repo
already exists), not `ensure_repo()`'s initial-commit path. This spec
covers the gap that fix didn't reach.

## [S2] Solution

`ensure_repo()`'s initial commit gets `--allow-empty`:

```python
await self._run(
    "commit", "--allow-empty", "-m", "Initial commit",
    f"--author={self.author_name} <{self.author_email}>",
)
```

An empty initial commit is a normal, deliberate git pattern for
"establish the repo root even with nothing in it yet" — exactly this
case (a workflows/actions/connectors dir waiting for content that may
never come, e.g. a base install with no content-pack). No behavior
change for the non-empty case (`git add .` still stages real files when
they exist, and the commit still records them).

## [S3] Non-goals

- Not touching `commit()` — already fixed, out of scope here.
- Not changing `_run()`'s error-message construction (stdout not
  included) — the empty-message symptom disappears once the underlying
  commit stops failing; not worth a separate change for a case that no
  longer occurs.
