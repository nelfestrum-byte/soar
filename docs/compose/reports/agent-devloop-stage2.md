---
feature: agent-devloop-stage2
date: 2026-07-22
spec: docs/compose/specs/2026-07-22-agent-devloop-stage2-design.md
plan: docs/compose/plans/2026-07-22-agent-devloop-stage2.md
---

# Report: Agent Dev-Loop — Этап 2

## What was built

Three extensions closing P3 and P4 from `UPGRADE.md` — the system now
explains itself to an agent without requiring it to read source files:

- **Общий модуль интроспекции** (`orchestrator/core/introspect.py`, new):
  `parse_classes`/`parse_functions`/`_signature`/`_summary` moved out of
  `orchestrator/api/tools.py` verbatim (no behavior change), plus a new
  `parse_functions` for top-level functions. `tools.py` now imports from
  this module instead of holding a local copy; `GET /tools`,
  `GET /tools/{name}` are unchanged (regression-tested by the existing
  `test_tools_api.py`, which passes unmodified).
- **`describe` for actions and connectors** (`orchestrator/api/actions.py`,
  `orchestrator/api/connectors.py`): `GET /actions` and `GET /connectors`
  list items now carry a `summary` (first docstring line, parsed via
  `parse_functions`/`parse_classes`, `""` on parse error or missing
  entry point — never a 500). New `GET /actions/{name}/describe` and
  `GET /connectors/{name}/describe` (both `_RO`) return full
  signature/docstring (actions) or constructor + methods + class
  docstring (connectors), 404 if the file/class isn't found — including
  the case where a file exists but its function/class name doesn't match
  what the registry expects.
- **Workflow docstring in meta** (`soar/workflows/__init__.py`,
  `orchestrator/models/workflow_meta.py`, `orchestrator/main.py`,
  `orchestrator/api/workflows.py`): `WorkflowRegistry.list()` now reads
  `cls.__doc__` (classes are already imported for registration, no new
  import cost); `WorkflowMeta` gained a `docstring: str = ""` field
  threaded through `load_workflow_metas`; `GET /workflows` and
  `GET /workflows/{name}` include it.
- **System + user prompt** (`orchestrator/api/prompts.py`, new;
  `orchestrator/prompts/system_prompt.md`, new;
  `orchestrator/config.py::SoarConfig.system_prompt_path`): `GET
  /prompts/system` serves a static, versioned-with-code markdown file
  (deliberately placed under `orchestrator/`, not `docs/`, because
  `deploy/prod/Dockerfile.orchestrator` and
  `deploy/stage/Dockerfile.orchestrator` only `COPY orchestrator/ ...`
  and never copy `docs/` — a file there would silently not exist in the
  deployed image). The file covers all 6 points from spec [S6]: what
  SOAR is, the three entity contracts (action = file-named function,
  connector = `BaseConnector` subclass, workflow = registry-keyed-by-
  filename), the Stage-1 dev loop (validation-before-write, full
  traceback, history/diff/restore), Stage-2 self-description endpoints,
  operational conventions (`dry_run`, lazy `_ensure_connected()`, stable
  webhook tokens), and known risks P6 (connector secrets returned in
  plaintext) and P10 (no concurrent-edit locking, last-write-wins).
  `GET /prompts/user` / `PUT /prompts/user` (admin) follow the same
  git-committed-file pattern as workflow/action/connector code, storing
  `prompts/user_prompt.md` in `config.git.workflows_repo`; deliberately
  no history/diff/restore for the user prompt (justified in spec [S6] —
  a bad prompt doesn't break entity registration the way bad code does).

## Verification

- `python -m pytest tests/orchestrator/ tests/soar/ -q` (excluding the
  5 connector test modules that fail to *collect* for missing optional
  third-party deps — `pymisp`, `pymysql`, `shodan`, `smbprotocol`,
  `winrm` — pre-existing on `main`, unrelated to this work): **453
  passed, 1 skipped, 1 failed**. The 1 failure
  (`tests/soar/tools/test_openapi.py::test_generate_config`) was
  independently re-run against a clean `main` checkout and fails
  identically there — confirmed pre-existing, not a regression (also
  documented as pre-existing in the Stage 1 report).
- `ruff check orchestrator/ soar/`: 8 findings, all pre-existing and
  outside this work's scope — 2 `B904` in `connectors.py`'s two
  `except UnicodeDecodeError` blocks (present before this change, same
  lines noted in the Stage 1 report), plus unrelated findings in
  `redis_queue.py`, `subprocess_runner.py`, `active_directory.py`,
  `wazuh.py`.
- New/extended test files: `tests/orchestrator/core/test_introspect.py`
  (new), `test_actions_api.py`, `test_connectors_api.py`,
  `test_workflows_api.py`, `tests/soar/test_workflows.py`,
  `tests/orchestrator/api/test_prompts_api.py` (new). One pre-existing
  test (`test_scenarios.py::test_scenario_5_action_crud_lifecycle`) was
  updated to match `GET /actions`'s new list-of-dicts shape (see
  deviations below).
- **[S9] success criteria — verified one by one:**
  - `GET /actions/{name}/describe` and `GET /connectors/{name}/describe`
    return signatures/docstrings without reading source — verified by
    `test_describe_action`, `test_describe_connector`.
  - `GET /actions`, `GET /connectors` include `summary` in list items —
    verified by `test_list_actions_includes_summary`,
    `test_list_connectors_includes_summary`.
  - `GET /workflows`, `GET /workflows/{name}` include workflow class
    `docstring` — verified by `test_list_and_get_workflow_include_docstring`
    and `tests/soar/test_workflows.py::test_workflow_registry_list_includes_docstring`.
  - `GET /prompts/system` serves a non-empty built-in prompt in one call,
    `_RO`-only — verified two ways: `test_prompts_api.py` (fixture file)
    **and** manually: started the dev server (`uvicorn orchestrator.main:app`)
    against a scratch config pointing `system_prompt_path` at the
    repository default, `curl http://127.0.0.1:8123/prompts/system`
    returned HTTP 200 with the real `orchestrator/prompts/system_prompt.md`
    content (confirmed non-empty, matches the file on disk), server then
    stopped.
  - `GET /prompts/user` defaults to `{"content": null}`; `PUT
    /prompts/user` (admin) saves with a git commit and an `AuditLog` row
    — verified by `test_get_user_prompt_defaults_to_null`,
    `test_put_user_prompt_saves_commits_and_audits`,
    `test_put_user_prompt_requires_admin`.
  - `GET /tools` behavior unchanged after the move to
    `core/introspect.py` — verified: `test_tools_api.py` passes
    unmodified.
  - All existing tests pass (see failure list above — confirmed
    pre-existing, unrelated); new tests cover [S3]–[S6].

## Notable deviations from the plan

- **`GET /actions` list shape.** The spec's [S4] wording ("добавить
  `summary` в элемент списка") implicitly assumes list items are already
  objects, matching the pattern already used by `GET /connectors`. The
  actual pre-Stage-2 `GET /actions` returned a bare list of filename
  strings, not objects — there was nowhere to attach a `summary` field
  without changing the element type from `str` to `dict`. Converted list
  items to `{"name": ..., "summary": ...}` and updated the one
  pre-existing test that depended on the old string-list shape
  (`test_scenarios.py::test_scenario_5_action_crud_lifecycle`), the same
  category of collateral fix the Stage 1 report already used as
  precedent for this project.
- No other deviations — [S3]–[S6] were implemented as specified,
  including exact function/route signatures from the spec's code
  snippets.
