# Plan: Agent Dev-Loop — Этап 1

Spec: [`docs/compose/specs/2026-07-22-agent-devloop-stage1-design.md`](../specs/2026-07-22-agent-devloop-stage1-design.md)

## Phase 1 — P1: валидация кода перед сохранением

- [x] `tests/orchestrator/api/test_validation.py` — добавить кейсы для
  новых `validate_workflow_code`/`validate_action_code`/
  `validate_connector_code`: syntax error → 422 с текстом; валидный
  класс/функция → без исключения; класс без нужного базового класса →
  422 (падает — функций ещё нет)
- [x] `orchestrator/api/validation.py` — добавить `_parse_or_422`,
  `validate_workflow_code`, `validate_action_code(code, name)`,
  `validate_connector_code` (как в [S3] спека, `ast.parse`, без импорта)
- [x] Расширить `tests/orchestrator/api/test_workflows_api.py`: невалидный
  код (syntax error, класс без нужного base) → `PUT
  /workflows/{name}/code` возвращает 422, файл не создан
- [x] Расширить `tests/orchestrator/api/test_actions_api.py`: то же для
  `PUT /actions/{name}` (нет функции с именем name → 422)
- [x] Расширить `tests/orchestrator/api/test_connectors_api.py`: то же
  для `PUT /connectors/{name}/code`
- [x] `orchestrator/api/workflows.py::save_workflow_code` — вызвать
  `validate_workflow_code(code)` сразу после `if not code.strip()`, до
  `os.makedirs`/`open(..., "w")`
- [x] `orchestrator/api/actions.py::save_action` — вызвать
  `validate_action_code(code, name)` в том же месте
- [x] `orchestrator/api/connectors.py::save_connector_code` — вызвать
  `validate_connector_code(content)` после null-byte-проверки
- [x] `python -m pytest tests/orchestrator/api/test_validation.py
  tests/orchestrator/api/test_workflows_api.py
  tests/orchestrator/api/test_actions_api.py
  tests/orchestrator/api/test_connectors_api.py -v`

## Phase 2 — P2: traceback в результате job

- [x] `tests/soar/test_workflows.py` — тест: workflow, у которого `run()`
  бросает исключение, даёт `WorkflowResult.traceback` — непустая строка,
  содержит имя исключения (падает — поля ещё нет)
- [x] `soar/workflows/base.py` — добавить `traceback: str | None = None` в
  `WorkflowResult`, `import traceback`, в `except Exception as e:` внутри
  `execute()` передать `traceback=traceback.format_exc()`
- [x] Новый `tests/soar/test_runner.py` — `main()` при ошибке до
  `workflows.execute()` (workflow не найден в реестре) печатает валидный
  JSON с непустым `error`, `sys.exit(1)` (запускать как subprocess или
  импортировать модуль с моканным `os.environ`/`sys.argv` — смотреть, как
  уже устроен `soar/runner.py`, вызывать `main()` напрямую после
  подмены `SOAR_WORKFLOW_NAME`/`SOAR_CONTEXT` в `os.environ` и перехвата
  stdout)
- [x] `soar/runner.py::main()` — обернуть `workflows.execute(...)` и сборку
  `output` в try/except Exception; при успехе `output["error"] =
  result.traceback or str(result.error)`; при исключении до
  `execute()` — `output = {"success": False, "workflow_name":
  workflow_name, "duration_seconds": None, "data": None, "error":
  traceback.format_exc()}`; `print(json.dumps(output))`,
  `sys.exit(1)` если `not output["success"]`
- [x] `python -m pytest tests/soar/test_workflows.py
  tests/soar/test_runner.py -v`

## Phase 3 — P8: история/diff/restore через API

- [x] `tests/orchestrator/test_git_manager.py` — расширить
  `test_git_manager_commit_author_override`-подобным тестом:
  `restore(filepath, commit, author_name=..., author_email=...)` коммитит
  под указанным автором (падает — `restore` пока не принимает эти kwargs)
- [x] `orchestrator/core/git_manager.py::restore` — расширить сигнатуру
  `author_name`/`author_email`, прокинуть в `self.commit(...)` (как в [S5])
- [x] Новый `tests/orchestrator/test_history.py` — `list_history`/
  `get_version`/`diff_versions`/`restore_version` против реального
  git-репо во временной директории (тот же паттерн, что
  `test_git_manager.py`: реальный `GitManager`, не мок); покрыть 404 при
  несуществующей версии/неудачном diff/restore
- [x] Новый `orchestrator/core/history.py` — `list_history`,
  `get_version`, `diff_versions`, `restore_version` как в [S5]
- [x] `orchestrator/api/workflows.py`:
  - `RestoreRequest(BaseModel)` с полем `commit: str`
  - `GET /{name}/code/history`, `GET /{name}/code/history/{commit}`,
    `GET /{name}/code/diff?a=&b=` на `_RO`, вызывают `history.*` над
    `workflows/{name}.py`; `validate_commit` на все commit-параметры
  - `POST /{name}/code/restore` на `_ADMIN` — `restore_version`, затем тот
    же reload, что и `PUT .../code` (`load_workflow_metas` +
    `job_manager.set_metas` + `scheduler.reload`), плюс
    `audit.record("workflow.restore", ...)`
- [x] `orchestrator/api/actions.py` — те же 4 роута над
  `actions/{name}.py`, restore без reload (как текущий `PUT`), audit
  action `action.restore`
- [x] `orchestrator/api/connectors.py` — 8 роутов: `code/history[/{commit}]`,
  `code/diff`, `code/restore` над `connectors/{name}/{name}.py` (audit
  `connector.restore_code`); `config/history[/{commit}]`, `config/diff`,
  `config/restore` над `connectors/{name}/{name}.yml` (audit
  `connector.restore_config`); оба restore без reload
- [x] Расширить `test_workflows_api.py`/`test_actions_api.py`/
  `test_connectors_api.py` — по одному тесту на history/diff/restore на
  каждую сущность: сохранить дважды (реальный `GitManager` на tmp-репо,
  подменить `app.state.git` локально в тесте — conftest даёт `AsyncMock`),
  откатиться на первую версию, проверить `GET .../code` вернул исходное
  содержимое; RBAC — 403 для non-admin на restore, 200 для `_RO`-ролей на
  history/diff (переопределить `get_current_user` на non-admin в
  конкретном тесте)
- [x] `python -m pytest tests/orchestrator/test_git_manager.py
  tests/orchestrator/test_history.py tests/orchestrator/api/ -v`

## Phase 4 — P9: персистентный webhook-токен

- [x] Новый `tests/orchestrator/test_workflow_state.py` —
  `parse_enabled`/`parse_token` на трёх форматах (legacy string, bool,
  dict); `save_state` пишет объектный формат с токеном только для
  webhook-типа; `load_state`/`remove_from_state` round-trip на tmp-файле
- [x] Новый `orchestrator/core/workflow_state.py` — `load_state`,
  `parse_enabled`, `parse_token`, `save_state`, `remove_from_state` как в
  [S6]
- [x] Расширить `tests/orchestrator/test_workflow_meta.py` (или новый
  `test_load_workflow_metas.py`) — `load_workflow_metas` вызванный дважды
  подряд с тем же `orchestrator_state.yaml` сохраняет тот же
  webhook-токен; токен меняется, только если файл состояния вручную
  удалён/очищен
- [x] `orchestrator/main.py::load_workflow_metas` — заменить инлайновое
  чтение `orchestrator_state.yaml` на `workflow_state.load_state`;
  `enabled = workflow_state.parse_enabled(saved)`; для `type ==
  "webhook"` предпочитать `workflow_state.parse_token(saved)` токену из
  `wf_info.get("token")`; в конце функции —
  `workflow_state.save_state(config, soar_metas)` перед `return`
- [x] `orchestrator/api/workflows.py` — `enable_workflow`/
  `disable_workflow`/`delete_workflow_code` переключить на
  `workflow_state.save_state(config, job_manager.list_metas())` /
  `workflow_state.remove_from_state(config, name)`; удалить локальные
  `_save_state`/`_remove_from_state`
- [x] Тест: сохранить webhook-workflow дважды подряд через `PUT
  /workflows/{name}/code`, сравнить `token` из `GET /workflows/{name}` до
  и после второго сохранения — должен совпасть
- [x] `python -m pytest tests/orchestrator/ tests/soar/ -v`

## Phase 5 — Full verification

- [x] `python -m pytest tests/orchestrator/ tests/soar/ -v` (полный прогон)
- [x] `ruff check orchestrator/ soar/`
- [x] Свериться с [S9] критериями успеха спека — по каждому пункту
