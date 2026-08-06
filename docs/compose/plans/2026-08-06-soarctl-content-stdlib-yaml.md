# Plan: remove the `yaml` host dependency from `soarctl content`

Spec: `docs/compose/specs/2026-08-06-soarctl-content-stdlib-yaml-design.md`

- [x] `tests/deploy/test_content_cli.py`: add an `instance` fixture (`tmp_path`
      with `docker-compose.yml` + `.env` so `compose_argv` doesn't raise),
      extend `_FakeVolume.run` to handle
      `["docker", "compose", ..., "exec", "-T", "orchestrator", "python3", "-c", ...]`
      by running `yaml.safe_load`/`yaml.safe_dump` against `kw["input_text"]`
      and returning the result as `.stdout`; update every existing
      `content.install(...)` / `content.list_installed()` / `content.remove(...)`
      call site to pass `instance`. Run the suite — expect failures (signatures
      don't take `instance` yet, `content.py` still imports `yaml` directly).
- [x] `deploy/soarctl_lib/content.py`:
  - remove `import yaml`
  - add `from .compose import compose_argv` and `import json`
  - add `_yaml_to_json(instance, yaml_text) -> dict` and
    `_json_to_yaml(instance, data) -> str` per [S3]
  - thread `instance: Path` through `install`, `list_installed`, `remove`,
    `_read_current_state`, `_read_manifest`; replace the four
    `yaml.safe_load`/`yaml.safe_dump` call sites with the new helpers
- [x] `deploy/soarctl_lib/cli.py`: add `_add_dir_arg` to `ct_install`,
      `ct_list` (capture the parser in a variable first), `ct_remove`;
      pass `paths.instance_dir(args)` into the three `content.*` calls
- [x] Re-run `tests/deploy/test_content_cli.py` — green
- [x] Import audit: confirm no `deploy/soarctl_lib/*.py` module imports
      anything outside stdlib (repeat the grep from the spec's [S1])
- [x] `docs/compose/reports/soarctl-content-stdlib-yaml.md` — what changed,
      what was verified, any judgment calls

## [S5] `soar-content-pack` sibling missing on build (found while verifying on the real prod host)

- [x] `tests/deploy/test_soarctl_bundle.py`: add a test asserting
      `build_images` falls back to an empty directory as the `basepack`
      build context when `repo_root.parent / "soar-content-pack"` doesn't
      exist, and a second test asserting it uses the real sibling directory
      when present
- [x] `deploy/soarctl_lib/bundle.py::build_images` — fall back to
      `tempfile.mkdtemp()` when the sibling pack directory is missing
- [x] Re-run `tests/deploy/test_soarctl_bundle.py` — green
