# Bug Fix: `soarctl` crashes on hosts without `pyyaml`

> [!NOTE]
> Спек по итогам прод-инцидента (`ModuleNotFoundError: No module named 'yaml'`
> на `./soarctl --help`, 2026-08-06). Только фикс, без рефакторинга.
> Plan: `docs/compose/plans/2026-08-06-soarctl-content-stdlib-yaml.md`

## [S1] Problem

`deploy/soarctl_lib/content.py:33` does `import yaml` at module level.
`deploy/soarctl_lib/cli.py:11` imports `content` eagerly along with every
other subcommand module, so **any** `soarctl` invocation — including
`--help` — imports `yaml` transitively, whether or not the user is running
a `content` subcommand.

The host-side `soarctl` CLI is designed to be stdlib-only —
`docs/compose/specs/2026-07-22-deploy-cli-design.md` line 70: "Host-слой —
сам `soarctl`: Python на stdlib". This is what lets `soarctl` run against a
bare `python3` on a fresh prod host (`git clone` + run, no venv, no `pip
install` step — consistent with principle 4 in `AGENTS.md`, no runtime
package installs). An import audit of every `deploy/soarctl_lib/*.py`
module confirms `content.py` is the **only** violation — every other
module (`backup.py`, `bundle.py`, `compose.py`, `doctor.py`, `env.py`,
`git_source.py`, `migrate.py`, `paths.py`, `prompts.py`, `runner.py`,
`status.py`, `users.py`) sticks to stdlib.

It went unnoticed because dev/CI always runs `soarctl` from the project's
own venv, which has `pyyaml` anyway (`orchestrator/requirements.txt`,
`soar/requirements.txt`). A prod host that only ever ran `git clone` +
`./soarctl init/up` — the exact on-site flow
`docs/compose/specs/2026-07-29-soarctl-inplace-onsite-design.md` was
written for — has no reason to have `pyyaml` on its system `python3`, and
`soarctl` crashes on first use.

**Immediate workaround** (unblocks a stuck host today, not part of this
fix): `pip3 install --user pyyaml` (or `apt-get install python3-yaml`) on
the host running `soarctl`.

## [S2] Why `content.py` needs YAML at all

`content.py` reads/writes two YAML documents:
- `manifest.yaml` at the root of a content pack (author-supplied, arbitrary
  valid YAML — comments, anchors, flow style are all fair game since packs
  aren't authored by this codebase)
- `.soar-content.yaml`, the install marker this module itself writes and
  later reads back (schema fully controlled by `content.py`)

Hand-rolling a YAML parser/emitter to avoid the dependency is out — a
manifest is arbitrary author-supplied YAML, and "half-implement YAML
ourselves" is a worse bug than the one being fixed.

## [S3] Fix: proxy to the orchestrator container, like `users.py` already does

`deploy/soarctl_lib/users.py` already solves exactly this class of problem
for `orchestrator.auth.cli`: rather than reimplementing user/auth logic on
the host, it shells out to the already-running container that has the
code and its dependencies (`docker compose exec orchestrator python -m
orchestrator.auth.cli ...`, via `compose.compose_argv`). The orchestrator
container already carries `pyyaml` (`orchestrator/requirements.txt`,
baked into the image at build time — a versioned contract, not a runtime
install, per principle 4). `content.py` should use the same proxy pattern
instead of importing `yaml` on the host.

Two small helpers replace every `yaml.safe_load`/`yaml.safe_dump` call:

```python
def _yaml_to_json(instance: Path, yaml_text: str) -> dict:
    """Parses YAML inside the orchestrator container, returns the result as
    a stdlib-parseable JSON string — host only ever touches JSON."""
    argv = compose_argv(instance, "exec", "-T", "orchestrator", "python3", "-c",
                         "import sys, json, yaml; json.dump(yaml.safe_load(sys.stdin.read()) or {}, sys.stdout)")
    result = run(argv, input_text=yaml_text)
    return json.loads(result.stdout)


def _json_to_yaml(instance: Path, data: dict) -> str:
    argv = compose_argv(instance, "exec", "-T", "orchestrator", "python3", "-c",
                         "import sys, json, yaml; yaml.safe_dump(json.loads(sys.stdin.read()), sys.stdout, sort_keys=False)")
    result = run(argv, input_text=json.dumps(data))
    return result.stdout
```

`-T` (disable pseudo-tty allocation) is required — without it `docker
compose exec` won't let us pipe `input_text` through stdin non-interactively.

Every function in `content.py` that currently takes no `instance` argument
(`install`, `list_installed`, `remove`, and the private `_read_current_state`/
`_read_manifest`) gains one, threaded through the same way `backup.py` and
`users.py` already do it — `cli.py` resolves it once via
`paths.instance_dir(args)` and passes it down. This is also, incidentally,
a **correctness** fix, not just a dependency one: `content install/list/remove`
currently has no `--dir` flag at all (unlike every sibling subcommand), so
today it silently assumes cwd conventions it never checks; requiring
`instance` makes it consistent with `backup`/`users`/`migrate`.

Net effect: `content install/list/remove` now requires the target
instance's orchestrator container to be running (`docker compose exec`
needs a live container) — a stricter precondition than today's "just needs
the `soar-data` volume to exist," but a reasonable one: installing content
into an instance that isn't up isn't a supported flow, and `backup`/`users`
already have this exact precondition.

`import yaml` is removed from `content.py` entirely. No other file in
`deploy/soarctl_lib/` imports it, so the host-stdlib-only invariant is
fully restored.

## [S4] Testing

`tests/deploy/test_content_cli.py` mocks `content.run` (the `_FakeVolume`
fixture) and separately imports `yaml` at the top for building test
fixtures (fine — tests run inside the dev venv, which has `pyyaml`; only
the *host* runtime path is constrained). Extend `_FakeVolume.run` to also
handle the new `docker compose exec ... python3 -c ...` calls by actually
calling `yaml.safe_load`/`yaml.safe_dump` against `input_text` and
returning it as `stdout` — this keeps the "no real docker, no real
subprocess" testing convention (`AGENTS.md`) while exercising the real
code path (host builds/parses JSON, "container" does the YAML step).

Need a fake instance directory (`docker-compose.yml` + `.env`, so
`compose_argv` doesn't raise `ComposeError`) — add a `tmp_path`-based
fixture alongside the existing `_make_pack` helper.

Every existing test in the file calls `content.install/list_installed/remove`
without an `instance` argument — all call sites need updating once the
signature changes.

## [S5] Related bug found during the same rollout: missing `soar-content-pack` sibling

While reproducing this on the reporting prod host, `./soarctl install`
(git-sourced on-site install) failed one step later with a different error:

```
ERROR: failed to get build context basepack: stat /root/soar-content-pack: no such file or directory
```

`deploy/soarctl_lib/bundle.py::build_images` passes
`--build-context basepack=<repo_root>/../soar-content-pack` unconditionally
— that sibling directory only exists on dev machines that happen to have
`soar-content-pack` checked out next to this repo (it's a local-only repo
with no remote, per `AGENTS.md`). `bundle.py`'s own docstring already
flagged this path as "UNVERIFIED against a real `docker build`"; this is
that verification, and it failed exactly as an unverified path would.

Fix (folded into this same rollout, not a separate spec — same root cause
category: an on-site path that was never exercised against a real host):
`build_images` now falls back to an empty temp directory when the sibling
is missing. This is a supported, not a degraded, path — `COPY --from=basepack`
only needs the context to exist, and `orchestrator/main.py::seed_connector_pack`
already treats a missing `manifest.yaml` as "skip seeding" (it was written
for exactly this case). Net effect: `soarctl install` now produces a
working instance with zero built-in connectors when no content pack is
present, installable later via `soarctl content install <pack>`.
