# Plan: PIP_INDEX_URL override for `docker build`

Spec: `docs/compose/specs/2026-08-06-pip-index-mirror-design.md`

- [x] `tests/deploy/test_soarctl_bundle.py`: add
      `test_build_images_passes_pip_index_url_when_env_set` — monkeypatch
      `os.environ["PIP_INDEX_URL"]`, assert the orchestrator `docker build`
      call contains `--build-arg PIP_INDEX_URL=<value>`.
- [x] `tests/deploy/test_soarctl_bundle.py`: add
      `test_build_images_omits_pip_index_url_build_arg_when_env_unset` —
      ensure `PIP_INDEX_URL` is absent from `os.environ`, assert no
      `--build-arg` starting with `PIP_INDEX_URL=` appears in either build
      call. (Existing tests already assert exact build-call shape in
      places — check they don't need updating for the new conditional arg.)
- [x] Run both new tests, confirm they fail against current `bundle.py`
      (`build_images` doesn't read the env var yet).
- [x] `deploy/prod/Dockerfile.orchestrator`: add
      `ARG PIP_INDEX_URL=https://pypi.org/simple` near the top (single-stage
      build, so one declaration covers both `RUN pip install` steps), add
      `--index-url "$PIP_INDEX_URL"` to both the `platform-venv` and
      `content-venv` pip installs.
- [x] `deploy/soarctl_lib/bundle.py::build_images`: read
      `os.environ.get("PIP_INDEX_URL")`; if set, insert
      `["--build-arg", f"PIP_INDEX_URL={value}"]` into the orchestrator
      `docker build` argv before `-t`. UI build untouched (no pip).
- [x] Run the full `tests/deploy/` suite, confirm green including the two
      new tests.
- [x] `deploy/prod/README.md`: document `PIP_INDEX_URL` under "On-site
      install" — one paragraph, example with `mirror.yandex.ru/pypi/simple`,
      note it's an env var read at `docker build` time, not persisted
      anywhere.
- [x] `deploy/prod/README.md` deleted per follow-up request (2026-08-06,
      same day) — content, including the `PIP_INDEX_URL` paragraph above,
      folded into `README.md` under "Деплой — soarctl"; `AGENTS.md` and
      `deploy/soarctl_lib/git_source.py`'s error message updated to point
      at `README.md` instead.
- [x] Report: `docs/compose/reports/pip-index-mirror.md`.
