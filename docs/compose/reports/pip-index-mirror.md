# Report: PIP_INDEX_URL override for `docker build`

Spec: `docs/compose/specs/2026-08-06-pip-index-mirror-design.md`
Plan: `docs/compose/plans/2026-08-06-pip-index-mirror.md`

## What happened

Reported failure: `./soarctl install` on a fresh Debian 13 prod host failed
at the `docker build` step for `soar-orchestrator` — `pip install` inside
the image retried against `pypi.org` five times (`ReadTimeoutError`) then
gave up (`No matching distribution found for fastapi`).

Diagnosed live on a second host reproducing the same symptom
(`admsec@192.168.1.78`, SSH):

- `pypi.org:443` — TLS ClientHello sent, connection then hangs to timeout
  (no RST) — consistent with SNI-based DPI filtering targeting that domain.
- `files.pythonhosted.org:443` (same CDN edge, actual wheel-download host),
  `deb.debian.org:443` (used by the earlier `apt-get` layer in the same
  build) — both connect fine.
- `pypi.org:80` — connects, 302 redirect to https.

Confirmed not a proxy/general-connectivity issue: no proxy env vars set, no
`/etc/docker/daemon.json` proxy config, other HTTPS domains on the same CDN
reachable.

## What changed

- `deploy/prod/Dockerfile.orchestrator`: `ARG PIP_INDEX_URL=https://pypi.org/simple`,
  passed to both `pip install` calls (`platform-venv`, `content-venv`) via
  `--index-url "$PIP_INDEX_URL"`.
- `deploy/soarctl_lib/bundle.py::build_images`: reads `PIP_INDEX_URL` from
  the environment; when set, forwards it as `--build-arg` to the
  orchestrator build only (UI build has no `pip` step). When unset, no
  `--build-arg` is added — the Dockerfile's own default applies, matching
  behavior before this change for every deployer who doesn't opt in.
- `deploy/prod/README.md`: documented under "On-site install", with a
  `mirror.yandex.ru/pypi/simple` example. Later the same day, the whole
  file was deleted at the user's request ("мусорный файл") and its
  content — including this paragraph — folded into `README.md` under
  "Деплой — soarctl"; `AGENTS.md` and the error message in
  `deploy/soarctl_lib/git_source.py` were updated to point at `README.md`
  instead.
- `tests/deploy/test_soarctl_bundle.py`: two new tests — env set → correct
  `--build-arg` on the orchestrator build only; env unset → no
  `--build-arg` on either build. Both written and confirmed failing before
  the `bundle.py` change, passing after.

## Explicitly rejected

Defaulting the `ARG` itself to a third-party mirror (e.g. Yandex) — would
change the default package source for every deployer of this open-source
repo, not just hosts affected by SNI filtering. Kept `pypi.org` as the
Dockerfile default; the mirror is opt-in per build via the environment
variable.

## Verification

- `python -m pytest tests/deploy/` — 133 passed.
- Not verified: an actual `docker build --build-arg PIP_INDEX_URL=...`
  against a live mirror from a filtered network (the dev-lab host used for
  diagnosis wasn't used to re-run the full `soarctl install` end to end as
  part of this patch). Recommended next step for whoever hit the original
  report: `PIP_INDEX_URL=https://mirror.yandex.ru/pypi/simple ./soarctl install`
  on the affected host, confirm the image builds.
