# `soarctl`: in-place on-site instances (checkout == instance)

> Reworks the on-site half of
> `docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md`. That spec
> added `install --repo`/`update` as a second source for `soarctl install`,
> but kept the original `install <bundle>` model of "populate a separate
> instance directory" — for the on-site case this means a git checkout *and*
> a copied-out instance directory that aren't structurally connected. This
> spec removes that split for on-site: the checkout itself becomes the
> instance. The air-gapped bundle path
> (`docs/compose/specs/2026-07-22-deploy-cli-design.md`) is unchanged.

## [S1] Problem

The on-site flow documented in `deploy/prod/README.md` today is:

```bash
python deploy/soarctl install --repo . --dir soar-prod
cd soar-prod
python soarctl doctor
```

Three concrete problems, not just an ergonomics complaint:

1. **The last two lines don't work.** `git_source.install()` only copies
   `docker-compose.yml`/`config.yaml.template`/`VERSION`/`source.json` into
   `soar-prod/` — never `soarctl`/`soarctl_lib/` (see `bundle.package()` for
   contrast, which *does* bundle them for the air-gap case). `cd soar-prod &&
   python soarctl doctor` fails with "can't open file 'soarctl'". This has
   never been exercised end-to-end (the onsite-update report's manual
   verification stopped at the `docker build` call, before reaching this
   step).
2. **Two directories for one instance, with no structural link beyond a
   `source.json` file.** The checkout (source code, where you'd `git pull`)
   and the instance directory (`docker-compose.yml`, `.env`, `config.yaml`)
   are siblings at best, copies of each other's `deploy/prod/` at worst.
   Editing `deploy/prod/docker-compose.yml` in the checkout has no effect on
   the running instance — you'd need to know to re-run `install` to re-copy
   it. Nothing about the CLI communicates this.
3. **`--dir` and `--repo` both accept relative paths resolved against
   whatever the caller's cwd happens to be**, so "which directory am I
   supposed to be in" depends on which flag you're using, contradicting the
   `deploy/.gitignore` entries (`prod/config.yaml`, `prod/.env`) that already
   assume instance files live *inside* `deploy/prod/` in the checkout, not
   in a separately named directory.

## [S2] Solution

### Checkout is the instance — no copy step

For the on-site path, the instance directory is always
`<repo_root>/deploy/prod/` inside the git checkout itself — never a
separately named/located directory. `docker-compose.yml`,
`config.yaml.template`, `Dockerfile.orchestrator`, `Dockerfile.ui` are
already there (tracked in git); `soarctl install` no longer copies them
anywhere, it operates on them in place. `.env`/`config.yaml`/`VERSION`/
`source.json` are written into that same directory (already covered by
`deploy/.gitignore`, except `VERSION`/`source.json` which need adding).

```bash
git clone <url> soar && cd soar
./soarctl install                 # git checkout <ref> if given, docker build, write VERSION+source.json
./soarctl init --interactive      # .env + config.yaml, same as today
./soarctl up
./soarctl migrate --fresh
./soarctl users create --username admin --role admin
```

No `--dir`, no `--repo <url>` clone-for-you, no `cd` into a second
directory. `git pull`/`git status`/editing `deploy/prod/docker-compose.yml`
by hand and `soarctl update` all operate on the one directory you're
standing in.

### `soarctl install` drops URL cloning

`git_source.install()` no longer accepts a git URL and no longer clones.
The user clones themselves (that's the point of "git clone style") —
`install` only ever operates on an *existing* checkout: cwd by default, or
an explicit local path via `--repo PATH` (rare — e.g. invoking `soarctl`
from outside the checkout). Removing the clone branch also removes the
`dest_dir/src` indirection entirely; there is no `dest_dir` parameter left,
only `checkout: Path`.

```python
def install(checkout: Path, ref: str | None) -> Path:
    if ref:
        run(["git", "-C", str(checkout), "checkout", ref])
    version = resolve_version(checkout)
    build_images(checkout, version)
    instance = checkout / "deploy" / "prod"
    (instance / "VERSION").write_text(version + "\n")
    (instance / _SOURCE_FILE).write_text(json.dumps({"checkout": str(checkout)}))
    return instance
```

### `soarctl` auto-discovers its working directory, like `git`

`paths.instance_dir(args)` currently is `Path(args.dir or ".").resolve()` —
correct only if the caller's cwd already *is* the instance directory. New
resolution order (`--dir` always wins when passed explicitly):

1. `--dir` given → use it as-is (escape hatch, both instance models).
2. Walk up from cwd; if some ancestor (including cwd) directly contains
   `docker-compose.yml`, that ancestor is the instance (covers: air-gapped
   bundle instances, which are self-contained by design, and the rare case
   of someone `cd`-ing straight into `deploy/prod`).
3. Otherwise walk up from cwd for `pyproject.toml` (reusing the same search
   `repo_root()` already does for `soarctl package`); if found and
   `<root>/deploy/prod/docker-compose.yml` exists, the instance is
   `<root>/deploy/prod`. This is what makes `soarctl status` work from
   `orchestrator/api/` two levels down, the same way `git status` does.
4. Falls back to cwd, resolved (today's behavior), so commands that operate
   *before* `deploy/prod/docker-compose.yml` exists (there is none anymore —
   the file is checked into git — but keep the fallback for the bundle path
   pre-`install`) still get a sane error from `compose.py`'s existing
   "not a soarctl instance directory" check rather than a stack trace from
   this function.

This one function change gives every subcommand (`up`, `status`, `migrate`,
`users`, `backup`, `update`, `doctor`, `logs`, `init`) location-independence
for free — none of their own code changes.

### Root-level `./soarctl` bash wrapper

```bash
#!/usr/bin/env bash
exec python3 "$(dirname "${BASH_SOURCE[0]}")/deploy/soarctl" "$@"
```

Added at repo root, executable bit set in git. Lets the on-site flow read
exactly like `git clone && cd && ./soarctl ...` — no `python deploy/soarctl`
prefix, no PATH/install step. `deploy/soarctl` itself is unchanged and still
works directly (needed for the air-gap bundle, where it's copied to the
instance directory without a repo root above it to put a wrapper in).

### `source.json` shape simplifies

Was `{"repo": "<--repo arg as typed>", "checkout": "<resolved path>"}` — the
`repo` field only ever mattered for cosmetic display of what the user typed
(URL or path). With cloning gone, `checkout` is always
`instance_dir.parent.parent`, so `source.json` only needs to keep it for
`update()`'s use, unchanged in shape: `{"checkout": "<repo_root>"}`.

## [S3] Non-goals

- **Air-gapped bundle path unchanged.** `soarctl package`/
  `install <bundle.tar.gz>` keep the copy-into-a-named-directory model —
  there is no checkout on that machine to merge with, by design (see
  `2026-07-22-deploy-cli-design.md` [S2]).
- **`deploy/stage/` unchanged** — separate `Makefile`-based QA-stand flow,
  out of scope here as it has been for every prior `soarctl` spec.
- **Multi-instance support** — still Known Limitation #8/#9. One checkout
  still means one instance (`<repo_root>/deploy/prod`); running two
  concurrent on-site instances from the same checkout is not supported,
  same as before this change.
- **Windows-native wrapper (`.cmd`/`.ps1`).** The bash wrapper targets the
  on-site deploy target (a Linux machine running Docker) — not this repo's
  own Windows dev environment. `python deploy/soarctl` keeps working
  everywhere as the fallback.
- **Re-litigating the migrate stamp/upgrade non-auto-detect decision** —
  unchanged, see prior specs.

## [S4] Testing strategy

- `paths.instance_dir()` — new tests for: walking up to find
  `docker-compose.yml` directly (bundle-style, from a nested cwd);
  walking up to find `pyproject.toml` then resolving to
  `<root>/deploy/prod` (checkout-style, from a nested cwd, e.g.
  `orchestrator/api/`); `--dir` still wins over both when passed; fallback
  to cwd when neither marker exists.
- `git_source.install()`/`update()` — rewritten tests replacing the
  URL-clone tests (removed, feature removed) with: installs in place under
  `<checkout>/deploy/prod` (no copy of `docker-compose.yml`, it already
  exists there — the test fixture places it there, `install` must *not*
  overwrite or recopy it); `source.json` has only `checkout`; `update()`
  tests otherwise unchanged (still exercise `_read_source` deriving the
  right checkout). All still mock `subprocess.run`/`build_images`, no live
  Docker/git.
- `cli.py` — `install`'s argparse no longer has a URL/clone branch to test;
  add a test that `--dir` still overrides auto-discovery for `install`,
  `up`, `status`, etc.
- End-to-end (manual, documented in the report, same precedent as prior
  `soarctl` specs): `git clone` a real local checkout to a scratch dir,
  `cd` into it, `./soarctl install && ./soarctl init && ./soarctl up &&
  ./soarctl migrate --fresh && ./soarctl users create ...`, then repeat
  `./soarctl status` from a subdirectory to confirm auto-discovery, then
  `./soarctl update` after a commit to confirm postgres/redis containers
  keep their `CreatedAt` (same check as the prior on-site-update spec).

## [S5] Success criteria

- [ ] `git clone <repo> X && cd X && ./soarctl install && ./soarctl init &&
      ./soarctl up` succeeds with zero `--dir`/`--repo` flags and zero
      "file not found" errors
- [ ] `soarctl status` (and every other subcommand) run from a subdirectory
      of the checkout resolve the same instance as running from the repo
      root — no `--dir` needed
- [ ] `soarctl install --repo <url>` no longer exists (removed, not
      deprecated with a shim — README documents `git clone` as the first
      step instead)
- [ ] Air-gapped bundle path (`package`/`install <bundle.tar.gz>`/every
      subcommand against a bundle-extracted instance) has zero behavior
      change
- [ ] `deploy/prod/README.md` on-site section reads as a single
      `git clone && cd && ./soarctl ...` sequence, no second directory
      mentioned
- [ ] `tests/deploy/` all pass; no test still asserts the removed
      URL-clone behavior
