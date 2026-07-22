# Plan: Agent Dev-Loop — Этап 2

Spec: [`docs/compose/specs/2026-07-22-agent-devloop-stage2-design.md`](../specs/2026-07-22-agent-devloop-stage2-design.md)

## Phase 1 — S3: общий модуль интроспекции

- [ ] `tests/orchestrator/core/test_introspect.py` (новый) — `parse_classes`
  на фикстурной строке (класс с методами/докстрингом, приватные методы
  пропущены); `parse_functions` на фикстурной строке (функция с
  докстрингом, приватные пропущены); оба — пустой файл → `[]` (падает —
  модуля ещё нет)
- [ ] `orchestrator/core/introspect.py` (новый) — `_signature`, `_summary`,
  `parse_classes`, `parse_functions` как в [S3]
- [ ] `orchestrator/api/tools.py` — удалить локальные `_signature`/
  `_summary`/`_parse_module`, импортировать `parse_classes`/`_summary` из
  `orchestrator.core.introspect`; `_parse_module` в `list_tools`/`get_tool`
  заменить на `parse_classes`
- [ ] `python -m pytest tests/orchestrator/core/test_introspect.py
  tests/orchestrator/api/test_tools_api.py -v` — старые тесты `/tools`
  проходят без изменений (регрессия на перенос кода)

## Phase 2 — S4: describe для actions и connectors

- [ ] Расширить `tests/orchestrator/api/test_actions_api.py`: `GET
  /actions` содержит `summary` на элементах; `GET
  /actions/{name}/describe` → `{name, signature, docstring, module}` для
  валидного action; `404` для несуществующего имени; `404` (не 500) если
  функция в файле не совпадает с именем файла (падает — ручки ещё нет)
- [ ] `orchestrator/api/actions.py` — добавить `summary` в `list_actions`
  (парсить каждый файл через `parse_functions`, искать функцию с именем
  файла, `""` при ошибке/отсутствии); новая `GET /{name}/describe` на
  `_RO` как в [S4]
- [ ] Расширить `tests/orchestrator/api/test_connectors_api.py`: `GET
  /connectors`/`GET /connectors/{name}` содержат `summary` при
  `has_code`; `GET /connectors/{name}/describe` → класс с `constructor`/
  `methods`/докстрингом; `404` для коннектора без `.py` (падает)
- [ ] `orchestrator/api/connectors.py` — добавить `summary` в
  `list_connectors`/`get_connector` (через `parse_classes` +
  `_parse_class_name`, `""` при ошибке); новая `GET
  /{name}/describe` на `_RO` как в [S4]
- [ ] `python -m pytest tests/orchestrator/api/test_actions_api.py
  tests/orchestrator/api/test_connectors_api.py -v`

## Phase 3 — S5: докстринг workflow в meta

- [ ] `tests/soar/test_workflows.py` — тест: `WorkflowRegistry.list()`
  возвращает `docstring` класса (непустая строка для класса с докстрингом,
  `""` без него) (падает — поля ещё нет)
- [ ] `soar/workflows/__init__.py::WorkflowRegistry.list()` — добавить
  `meta["docstring"] = cls.__doc__ or ""`
- [ ] `orchestrator/models/workflow_meta.py::WorkflowMeta` — добавить
  `docstring: str = ""`
- [ ] `orchestrator/main.py::load_workflow_metas` — передать
  `docstring=wf_info.get("docstring", "")` в `WorkflowMeta(...)`
- [ ] Расширить `tests/orchestrator/api/test_workflows_api.py`: `GET
  /workflows`/`GET /workflows/{name}` включают `docstring` (падает)
- [ ] `orchestrator/api/workflows.py::list_workflows`/`get_workflow` —
  добавить `"docstring": m.docstring`/`meta.docstring` в собираемые словари
- [ ] `python -m pytest tests/soar/test_workflows.py
  tests/orchestrator/api/test_workflows_api.py -v`

## Phase 4 — S6: системный и пользовательский промпт

- [ ] `orchestrator/config.py::SoarConfig` — добавить
  `system_prompt_path: str = "orchestrator/prompts/system_prompt.md"`
- [ ] Написать `orchestrator/prompts/system_prompt.md` — покрыть все 6
  пунктов из [S6] спека (что такое SOAR, контракт трёх типов сущностей,
  dev-loop Этапа 1, самоописание Этапа 2, конвенции dry_run/lazy-connect/
  webhook-токен, известные риски P6/P10)
- [ ] Новый `tests/orchestrator/api/test_prompts_api.py` — `GET
  /prompts/system` читает файл по `config.soar.system_prompt_path`
  (подменить путь на временный файл в фикстуре теста, не полагаться на
  реальный `system_prompt.md`), `404` если файла нет; `GET /prompts/user`
  → `{"content": null}` без файла; `PUT /prompts/user` требует `_ADMIN`
  (403 для viewer/analyst/service), пишет файл + git-commit + `AuditLog`;
  `GET /prompts/user` после `PUT` возвращает сохранённый контент (падает
  — роутера ещё нет)
- [ ] `orchestrator/api/prompts.py` (новый) — `get_system_prompt`,
  `get_user_prompt`, `save_user_prompt` как в [S6]
- [ ] `orchestrator/api/__init__.py` — экспортировать `prompts_router`
  (по аналогии с `tools_router`)
- [ ] `orchestrator/main.py` — `app.include_router(prompts_router)`
- [ ] `python -m pytest tests/orchestrator/api/test_prompts_api.py -v`
- [ ] Ручная проверка: поднять dev-сервер, `curl /prompts/system` —
  убедиться, что реальный `orchestrator/prompts/system_prompt.md`
  отдаётся не пустым

## Phase 5 — Full verification

- [ ] `python -m pytest tests/orchestrator/ tests/soar/ -v` (полный
  прогон, без регрессий в существующих тестах)
- [ ] `ruff check orchestrator/ soar/`
- [ ] Свериться с [S9] критериями успеха спека — по каждому пункту
