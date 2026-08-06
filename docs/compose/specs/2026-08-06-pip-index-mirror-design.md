# PIP_INDEX_URL override for `docker build`

## [S1] Problem

On-site install (`./soarctl install` from a git checkout, `README.md`
"Деплой — soarctl" → "On-site") builds `soar-orchestrator` locally via
`deploy/soarctl_lib/bundle.py::build_images`, which runs `docker build` on
`Dockerfile.orchestrator`. That Dockerfile's `pip install` step (both
`platform-venv` and `content-venv`) hits `pypi.org` unconditionally.

Reproduced on a dev-lab host (`admsec@192.168.1.78`): `docker build` failed —
`pip install` retried 5x against `pypi.org:443` with `ReadTimeoutError`, then
gave up (`No matching distribution found for fastapi`). Diagnosed directly on
the host:

- `pypi.org:443` — TLS ClientHello sent, then silence until timeout (no RST).
- `files.pythonhosted.org:443` (the actual wheel-download host) — connects
  fine.
- `deb.debian.org:443` (same build, `apt-get install` step) — connects fine.
- `pypi.org:80` (HTTP) — connects fine, 302 to https.

Selective failure of one domain over HTTPS while sibling CDN domains on the
same edge network succeed is consistent with SNI-based filtering upstream of
the host, not a general connectivity or DNS problem. There is currently no
way to point `docker build` at an alternate index without hand-editing
`Dockerfile.orchestrator`.

## [S2] Solution

Add a `PIP_INDEX_URL` build-arg to `Dockerfile.orchestrator`, defaulting to
`https://pypi.org/simple` — behavior for every existing build (nobody passes
`--build-arg`) is unchanged. `bundle.py::build_images` reads the
`PIP_INDEX_URL` environment variable on the machine running `soarctl`; when
set, it's forwarded as `--build-arg PIP_INDEX_URL=<value>` to the
orchestrator build. When unset, no `--build-arg` is passed at all and the
Dockerfile's own default applies — matching current behavior exactly for
every deployer who doesn't opt in.

`soarctl package`, `install` (on-site), and `update` all funnel through
`build_images`, so a single env-var check there covers all three call sites
without argparse changes to `cli.py`.

Out of scope: `Dockerfile.ui`'s `npm ci` (no `pip` involved, different
registry, not what broke on the dev-lab host); baking in any specific mirror
as a repo-wide default (rejected — see the alternatives below, this would
change the trust root for every deployer of this open-source project, not
just hosts behind SNI filtering).

## [S3] Alternatives considered

- **Default `ARG` to a third-party mirror (e.g. `mirror.yandex.ru`)** —
  rejected: changes the default package source for everyone who builds this
  repo, including hosts with no connectivity problem. Supply-chain trust
  root should default to the canonical index; opting into a mirror is a
  per-deployment decision, not a repo default.
- **CLI flag (`soarctl install --pip-index-url ...`)** — more discoverable
  than an env var, but touches `cli.py` argparse wiring across three
  subcommands (`package`/`install`/`update`) for a value that's really a
  build-environment property, not a per-invocation choice — same category as
  `http_proxy`/`https_proxy`, which are also read from the environment, not
  passed as flags. Env var chosen for consistency with that existing
  pattern and less surface area.

## [S4] Architecture

```
deploy/
├── prod/
│   └── Dockerfile.orchestrator   # MODIFY: ARG PIP_INDEX_URL, --index-url on both pip installs
└── soarctl_lib/
    └── bundle.py                 # MODIFY: build_images reads os.environ["PIP_INDEX_URL"],
                                   #         conditionally appends --build-arg
README.md                         # MODIFY: document the env var under "Деплой — soarctl" / On-site
tests/deploy/test_soarctl_bundle.py  # MODIFY: cover both the set and unset cases
```

## [S5] Non-goals

- No mirror config for `Dockerfile.ui`'s `npm` install.
- No persistence of the chosen mirror into `.env`/`config.yaml` — this is a
  build-time-only concern, not instance state; re-running `update` on a
  filtered network still needs `PIP_INDEX_URL` set in that shell.
