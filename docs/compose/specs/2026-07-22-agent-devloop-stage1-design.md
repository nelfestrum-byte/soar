# Agent Dev-Loop — Этап 1: замкнуть цикл разработки агента

> [!NOTE]
> Реализация Этапа 1 из `UPGRADE.md`. Закрывает P1, P2, P8, P9.
> Plan: `docs/compose/plans/2026-07-22-agent-devloop-stage1.md` (после этого спека).
> Роль агента на этом этапе — существующий `admin`, RBAC не трогаем (Этап 3).

## [S1] Problem

Агент пишет код через существующий CRUD API (`PUT /workflows/{name}/code`,
`PUT /actions/{name}`, `PUT /connectors/{name}/code`), но не может замкнуть
цикл «написал → узнал результат → откатился при ошибке» без чтения
серверных логов или файловой системы:

1. **Сохранение не проверяется.** `save_workflow_code`
   (`orchestrator/api/workflows.py:198-246`), `save_action`
   (`orchestrator/api/actions.py:76-114`), `save_connector_code`
   (`orchestrator/api/connectors.py:302-336`) пишут файл на диск сразу после
   декодирования тела запроса — единственная проверка — `code.strip()` не
   пустой. Ни синтаксис, ни наличие ожидаемой точки входа (класс-наследник
   для workflow/connector, одноимённая функция для action) не проверяются.
   Ответ — `{"status": "saved", ...}` в любом случае. Если код не
   импортируется, `WorkflowRegistry`/`ActionsRegistry`/`ConnectorRegistry`
   (`soar/workflows/__init__.py`, `soar/actions/__init__.py`,
   `soar/connectors/__init__.py`) молча логируют `_log.warning(...)` и не
   регистрируют сущность — агент увидит `200 saved` и не узнает, что сломал.

2. **Traceback недоступен агенту.** `soar/workflows/base.py:47-58`
   (`BaseWorkflow.execute`) ловит исключение из `self.run(context)` и кладёт
   в `WorkflowResult.error` сам объект `Exception`. `soar/runner.py:54-55`
   печатает в JSON только `str(result.error)` — одну строку без стека
   вызовов. `orchestrator/core/worker.py:88-99` парсит эту JSON-строку и
   кладёт в `job.result_error` (`orchestrator/models/job.py:28`), которое
   отдаётся как есть через `GET /jobs/{id}` (`orchestrator/api/jobs.py:62-68`,
   `WorkflowJob.to_dict()`). Чтобы узнать, на какой строке и с каким стеком
   упал workflow, агенту придётся читать файл лога джобы
   (`job.log_path`) как plain text вперемешку с любым stdout, который пишут
   actions/connectors — дорогая по контексту операция.

3. **История и откат недоступны через API.** `GitManager`
   (`orchestrator/core/git_manager.py`) уже реализует `history()` (строки
   85-102), `get_content()` (104-105), `diff()` (107-108), `restore()`
   (110-112) — вся механика готова и используется только `commit()` (53-83),
   вызываемым из PUT/DELETE роутов. Ни одна ручка не выставляет
   history/get_content/diff/restore наружу. Если агент сломал рабочий
   workflow, единственный способ увидеть прошлые версии и откатиться —
   зайти на сервер и работать с `git` напрямую.

4. **Webhook-токен нестабилен при частых правках.** Шаблон webhook-workflow
   (`orchestrator/api/workflows.py:37-39`, `WEBHOOK_TEMPLATE`) генерирует
   `token = secrets.token_urlsafe(32)` как атрибут класса — значение
   фиксируется при **импорте модуля**, не при первом создании файла. Каждый
   `save_workflow_code`/`reload_workflows` вызывает
   `load_workflow_metas(config)` (`orchestrator/main.py:99-143`), который
   заново импортирует `soar.workflows` (через `wf_registry.init()`) — токен
   пересоздаётся. `orchestrator_state.yaml` уже хранит per-workflow
   enabled/disabled (`_save_state`/`_remove_from_state`,
   `orchestrator/api/workflows.py:290-320`, читается в
   `load_workflow_metas:106,115`), но не токен — `meta.token` всегда берётся
   из `wf_info.get("token")` (`main.py:125`), то есть из свежего импорта
   класса. При агентской итеративной разработке (частые правки одного и
   того же webhook-workflow) внешняя система, знающая старый токен,
   перестаёт приниматься при каждом сохранении кода.

## [S2] Solution overview

Четыре независимых точечных расширения существующих механизмов — ни одно
не меняет модель исполнения (`soar.runner` subprocess, git-версионирование,
существующий admin-only доступ к коду):

1. **Валидация перед записью** ([S3]) — AST-парсинг (без импорта, тот же
   принцип, что уже применяется в `GET /tools`, `orchestrator/api/tools.py`)
   на синтаксис + наличие ожидаемой точки входа, до `open(filepath, "w")`.
2. **Traceback в существующем поле** ([S4]) — `WorkflowResult` получает
   поле `traceback`, `soar/runner.py` кладёт его в тот же JSON-ключ
   `"error"`, что и сегодня — `worker.py`/`job.result_error`/
   `GET /jobs/{id}` не меняются вообще.
3. **Read+restore API поверх `GitManager`** ([S5]) — тонкие роуты в
   `workflows.py`/`actions.py`/`connectors.py`, вызывающие уже готовые
   методы `GitManager` через новый общий модуль
   `orchestrator/core/history.py` (устраняет тройное дублирование одной и
   той же обёртки).
4. **Персистентный webhook-токен** ([S6]) — формат
   `orchestrator_state.yaml` меняется со строки (`"enabled"`/`"disabled"`)
   на объект (`{enabled, token}`); `load_workflow_metas` предпочитает
   сохранённый токен токену из свежего импорта класса.

## [S3] P1 — валидация кода перед сохранением

Новые функции в `orchestrator/api/validation.py` (уже содержит
`validate_name`/`validate_path_within` — естественное место):

```python
import ast

_WORKFLOW_BASES = {"BaseWorkflow", "ScheduledWorkflow", "WebhookWorkflow", "ManualWorkflow"}


def _parse_or_422(code: str, filename: str) -> ast.Module:
    try:
        return ast.parse(code, filename=filename)
    except SyntaxError as e:
        raise HTTPException(status_code=422, detail=f"Syntax error: {e}") from e


def validate_workflow_code(code: str) -> None:
    tree = _parse_or_422(code, "workflow.py")
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if bases & _WORKFLOW_BASES:
                return
    raise HTTPException(
        status_code=422,
        detail="No class inheriting BaseWorkflow/ScheduledWorkflow/WebhookWorkflow/ManualWorkflow found",
    )


def validate_action_code(code: str, name: str) -> None:
    tree = _parse_or_422(code, f"{name}.py")
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return
    raise HTTPException(
        status_code=422,
        detail=f"No function named '{name}' found (ActionsRegistry looks up by filename)",
    )


def validate_connector_code(code: str) -> None:
    tree = _parse_or_422(code, "connector.py")
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if "BaseConnector" in bases:
                return
    raise HTTPException(status_code=422, detail="No class inheriting BaseConnector found")
```

Использует `ast.parse`, не `compile()`/импорт — код никогда не исполняется
для проверки (тот же принцип, что `_parse_module` в `api/tools.py:21-49` и
`_parse_class_name` в `api/connectors.py:58-60`).

**Ограничение (принято сознательно, как и существующий
`_parse_class_name`):** проверка по имени базового класса в AST, не по
разрешённому импорту — `class X(BW)` с `from ... import BaseWorkflow as BW`
не будет распознан. Точное совпадение с тем, что реальный `issubclass()` в
registry делает лучше, но требует импорта (см. риск P5, не в этом плане).

**Точки вызова** — сразу после определения переменной `code`/`content`,
до `os.makedirs`/`open(..., "w")`:

- `save_workflow_code` (`workflows.py:198`) — `validate_workflow_code(code)`
  после строки 219 (`if not code.strip()`).
- `save_action` (`actions.py:76`) — `validate_action_code(code, name)` в том
  же месте.
- `save_connector_code` (`connectors.py:302`) — `validate_connector_code(content)`
  после null-byte-проверки (строка 320).

Конфиг коннектора (`.yml`, `save_connector_config`) не проверяется — вне
формулировки P1 (только код).

**Результат:** запись заведомо неисполняемого кода возвращает `422` с
текстом ошибки, файл не создаётся/не перезаписывается, git-коммита не
происходит. Существующее поведение при валидном коде не меняется.

## [S4] P2 — полный traceback в результате job

`soar/workflows/base.py`:

```python
import traceback

@dataclass
class WorkflowResult:
    success: bool
    workflow_name: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    error: Exception | None = None
    traceback: str | None = None   # new
    data: dict | None = None

    ...
    except Exception as e:
        ...
        return WorkflowResult(
            success=False,
            ...
            error=e,
            traceback=traceback.format_exc(),   # new
        )
```

`soar/runner.py::main()` — заменить `str(result.error)` на traceback, и
обернуть весь вызов `workflows.execute()` в try/except, чтобы ошибки
**до** входа в `BaseWorkflow.execute()` (класс не находится в реестре,
исключение в конструкторе `cls()` — `WorkflowRegistry.execute`,
`soar/workflows/__init__.py:108-113`) тоже давали структурированный JSON
вместо падения subprocess без финальной строки:

```python
import traceback as tb

def main():
    workflow_name = os.environ.get("SOAR_WORKFLOW_NAME", "")
    context = json.loads(os.environ.get("SOAR_CONTEXT", "{}") or "{}")

    try:
        result = workflows.execute(workflow_name, context)
        output = {
            "success": result.success,
            "workflow_name": result.workflow_name,
            "duration_seconds": result.duration_seconds,
            "data": result.data,
        }
        if result.error:
            output["error"] = result.traceback or str(result.error)
    except Exception:
        output = {
            "success": False,
            "workflow_name": workflow_name,
            "duration_seconds": None,
            "data": None,
            "error": tb.format_exc(),
        }

    print(json.dumps(output))
    if not output["success"]:
        sys.exit(1)
```

**Ничего ниже по цепочке не меняется:** `worker.py:88-99` уже парсит
последнюю JSON-строку лога и кладёт `parsed["error"]` в
`job.result_error` без изменений; `WorkflowJob.to_dict()`
(`orchestrator/models/job.py:36-52`) уже отдаёт `result_error`;
`GET /jobs/{id}` (`orchestrator/api/jobs.py:62-68`) уже возвращает его.
Расширение содержимого одного и того же поля контракта — ровно то, что
описано в `UPGRADE.md` P2, без новых полей/эндпоинтов.

## [S5] P8 — история/diff/восстановление через API

`GitManager.restore()` (`orchestrator/core/git_manager.py:110-112`)
сегодня не принимает автора — восстановление всегда коммитится от имени
дефолтного `config.git.author_name`, а не реального актора. Расширить
сигнатуру аналогично `commit()`:

```python
async def restore(
    self, filepath: str, commit: str,
    author_name: str | None = None, author_email: str | None = None,
) -> None:
    await self._run("checkout", commit, "--", filepath)
    await self.commit(
        filepath, f"Restore to {commit}",
        author_name=author_name, author_email=author_email,
    )
```

Новый общий модуль `orchestrator/core/history.py` — устраняет
дублирование одной и той же обёртки в трёх роутерах:

```python
from fastapi import HTTPException


async def list_history(git, filepath: str, limit: int = 20) -> list[dict]:
    commits = await git.history(filepath, limit=limit)
    return [
        {"hash": c.hash, "message": c.message, "author": c.author, "timestamp": c.timestamp}
        for c in commits
    ]


async def get_version(git, filepath: str, commit: str) -> str:
    try:
        return await git.get_content(filepath, commit)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=f"Version not found: {e}") from e


async def diff_versions(git, filepath: str, commit_a: str, commit_b: str) -> str:
    try:
        return await git.diff(filepath, commit_a, commit_b)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=f"Diff failed: {e}") from e


async def restore_version(
    git, filepath: str, commit: str, author_name: str, author_email: str,
) -> None:
    try:
        await git.restore(filepath, commit, author_name=author_name, author_email=author_email)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=f"Restore failed: {e}") from e
```

**Новые роуты** — read-роуты на существующих `_RO`-ролях (viewer/analyst/
service/admin, как и текущий `GET .../code`), restore — на `_ADMIN`
(как текущий `PUT`/`DELETE .../code`, RBAC не меняется в этом этапе):

| Метод | Путь | Действие |
|---|---|---|
| GET | `/workflows/{name}/code/history` | `list_history(git, f"workflows/{name}.py")` |
| GET | `/workflows/{name}/code/history/{commit}` | `get_version(...)` → `{"content": ...}` |
| GET | `/workflows/{name}/code/diff?a=&b=` | `diff_versions(...)` → `{"diff": ...}` |
| POST | `/workflows/{name}/code/restore` `{"commit": "..."}` | `restore_version(...)`, затем тот же reload что и `PUT .../code` (`load_workflow_metas`+`job_manager.set_metas`+`scheduler.reload`) + `audit.record("workflow.restore", ...)` |
| GET/GET/GET/POST | `/actions/{name}/history[/{commit}]`, `/actions/{name}/diff`, `/actions/{name}/restore` | то же на `actions/{name}.py`; без reload (текущий `PUT /actions/{name}` тоже не делает reload) + `audit.record("action.restore", ...)` |
| GET/GET/GET/POST | `/connectors/{name}/code/history[/{commit}]`, `/code/diff`, `/code/restore` | то же на `connectors/{name}/{name}.py`; без reload (как текущий `PUT .../code`) + `audit.record("connector.restore_code", ...)` |
| GET/GET/GET/POST | `/connectors/{name}/config/history[/{commit}]`, `/config/diff`, `/config/restore` | то же на `connectors/{name}/{name}.yml` + `audit.record("connector.restore_config", ...)` |

`restore` тело — `class RestoreRequest(BaseModel): commit: str` (по одной
модели на файл, как `GenerateRequest`/`PreviewRequest` уже определены в
`connectors.py:27-34`).

## [S6] P9 — персистентный webhook-токен

Новый модуль `orchestrator/core/workflow_state.py` — единственный читатель/
писатель `orchestrator_state.yaml`, заменяет текущие
`_save_state`/`_remove_from_state` (`orchestrator/api/workflows.py:290-320`)
и инлайновое чтение в `load_workflow_metas` (`orchestrator/main.py:99-104`).
Вынесено в `core/`, а не в `api/workflows.py`, чтобы `main.py` мог
импортировать на уровне модуля без цикличности (`workflows.py` уже сегодня
импортирует `orchestrator.main` лениво, внутри функций, именно из-за этого
риска).

```python
from pathlib import Path
import yaml


def _state_path(config) -> Path:
    return Path(config.soar.workflows_dir).parent / "orchestrator_state.yaml"


def load_state(config) -> dict:
    path = _state_path(config)
    if not path.exists():
        return {}
    with open(path) as f:
        return (yaml.safe_load(f) or {}).get("workflows", {})


def parse_enabled(value) -> bool:
    if isinstance(value, dict):
        return bool(value.get("enabled", True))
    if isinstance(value, str):
        return value == "enabled"
    return bool(value)


def parse_token(value) -> str | None:
    return value.get("token") if isinstance(value, dict) else None


def save_state(config, metas: list) -> None:
    path = _state_path(config)
    state = {"workflows": {}}
    for meta in metas:
        entry = {"enabled": meta.enabled}
        if meta.type == "webhook" and getattr(meta, "token", None):
            entry["token"] = meta.token
        state["workflows"][meta.name] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(state, f)


def remove_from_state(config, name: str) -> None:
    path = _state_path(config)
    if not path.exists():
        return
    with open(path) as f:
        state = yaml.safe_load(f) or {}
    workflows = state.get("workflows", {})
    if name in workflows:
        del workflows[name]
        state["workflows"] = workflows
        with open(path, "w") as f:
            yaml.dump(state, f)
```

Обратная совместимость: `parse_enabled`/`parse_token` принимают старый
строковый формат (`"enabled"`/`"disabled"`), новый объектный, и bool — файл
не в git (`orchestrator_state.yaml` — runtime-only, см. `CLAUDE.md`
Code rules), миграция не нужна, старые записи переписываются в новый
формат при первом же `save_state`.

`orchestrator/main.py::load_workflow_metas` — вместо инлайнового чтения
файла и `enabled = ... == "enabled"`, использовать `workflow_state.load_state`/
`parse_enabled`/`parse_token`; для `type == "webhook"` — предпочитать
токен из состояния токену из `wf_info.get("token")` (свежий импорт класса):

```python
state_workflows = workflow_state.load_state(config)
...
for wf_info in wf_registry.list():
    name = wf_info["name"]
    wf_type = wf_info["type"]
    saved = state_workflows.get(name, {})
    enabled = workflow_state.parse_enabled(saved)
    token = wf_info.get("token")
    if wf_type == "webhook":
        token = workflow_state.parse_token(saved) or token
    meta = WorkflowMeta(..., token=token, ...)
    soar_metas.append(meta)
...
workflow_state.save_state(config, soar_metas)   # persist resolved tokens immediately
return soar_metas
```

Финальный `save_state` в конце функции критичен: он персистит **впервые
сгенерированный** токен сразу при первой регистрации, а не откладывает до
следующего явного `enable`/`disable`/`save` — иначе рестарт оркестратора
до первого такого вызова всё ещё потерял бы токен.

`orchestrator/api/workflows.py` — `enable_workflow`/`disable_workflow`/
`delete_workflow_code` переключаются на
`workflow_state.save_state(config, job_manager.list_metas())`/
`workflow_state.remove_from_state(config, name)`; локальные
`_save_state`/`_remove_from_state` удаляются.

## [S7] Testing strategy

- `tests/orchestrator/api/test_validation.py` — новые случаи для
  `validate_workflow_code`/`validate_action_code`/`validate_connector_code`:
  синтаксическая ошибка → 422 с текстом; валидный класс/функция → без
  исключения; класс без нужного базового класса → 422.
- `tests/orchestrator/api/test_workflows_api.py`,
  `test_actions_api.py`, `test_connectors_api.py` — расширить `PUT`-тесты:
  невалидный код → `422`, файл не создан/не изменён, git-коммита нет.
- `tests/soar/test_workflows.py` — `BaseWorkflow.execute()` при исключении
  в `run()` заполняет `WorkflowResult.traceback` (непустая строка,
  содержит имя исключения).
- Новый `tests/soar/test_runner.py` — `main()` при ошибке до
  `workflows.execute()` (напр. отсутствующий workflow) печатает валидный
  JSON с непустым `error` и завершается с кодом 1 (было — необработанное
  исключение/трейс на stderr без финальной JSON-строки).
- `tests/orchestrator/test_git_manager.py` — расширить для
  `restore(..., author_name=..., author_email=...)`, проверить
  `GIT_AUTHOR_NAME` в результирующем коммите (тот же паттерн, что уже есть
  для `commit()`).
- Новый `tests/orchestrator/test_history.py` — `list_history`/
  `get_version`/`diff_versions`/`restore_version` против реального git-репо
  во временной директории (как уже делает `test_git_manager.py`).
- Расширить `test_workflows_api.py`/`test_actions_api.py`/
  `test_connectors_api.py` — по одному тесту на `history`/`diff`/`restore`
  на каждую сущность: сохранить код дважды, откатиться на первую версию
  через API, проверить `GET .../code` вернул исходное содержимое; RBAC
  (`403` для не-admin на `restore`, доступен для `_RO`-ролей на history/diff).
- Новый `tests/orchestrator/test_workflow_state.py` — `parse_enabled`/
  `parse_token` на трёх форматах (legacy string, bool, dict); `save_state`
  пишет объектный формат; `load_workflow_metas` (через
  `tests/orchestrator/test_workflow_meta.py` или новый тест) — токен
  сохраняется между двумя последовательными вызовами при неизменном
  состоянии, меняется только если `orchestrator_state.yaml` вручную
  очищен.

```bash
python -m pytest tests/orchestrator/ tests/soar/ -v
ruff check orchestrator/ soar/
```

## [S8] Non-goals (повтор границ этапа из UPGRADE.md)

- **P3/P4 (самоописание, системный промпт)** — Этап 2, не трогаем.
- **P7 (отдельная роль агента)** — Этап 3; все новые роуты в [S5]
  используют существующие `_RO`/`_ADMIN`, никаких новых ролей.
- **P5/P6/P10/P11** — риски, зафиксированные в реестре `UPGRADE.md` часть 3,
  этот этап их не закрывает и не увеличивает (валидация в [S3] не добавляет
  новый импорт кода в процесс оркестратора — использует только `ast.parse`).
- **Конфликты параллельного редактирования (P10)** — restore в [S5] не
  добавляет locking; последний коммит остаётся источником истины, как и
  сегодня для `PUT`.
- **Библиотека one-shot примеров, маскирование секретов, структурированные
  логи** — вне этого этапа (см. реестр рисков).

## [S9] Success criteria

- [ ] `PUT /workflows/{name}/code` / `PUT /actions/{name}` /
      `PUT /connectors/{name}/code` с синтаксически неверным или без
      ожидаемой точки входа кодом возвращают `422` с текстом ошибки, файл
      не создаётся/не перезаписывается
- [ ] Упавший `run()` workflow — `GET /jobs/{id}` возвращает `result_error`
      с полным traceback (файл, строка, тип исключения), не только
      `str(exception)`
- [ ] Ошибка до входа в `run()` (класс не найден, конструктор упал) тоже
      даёт структурированный `result_error`, а не падение subprocess без
      финальной строки в логе
- [ ] Для workflow/action/connector code и connector config доступны
      `history`/version-by-commit/`diff`/`restore` через API, без захода на
      сервер
- [ ] `restore` коммитится от имени реального актора (не фиксированного
      дефолта), пишет `AuditLog`-запись
- [ ] Повторное сохранение кода одного и того же webhook-workflow не меняет
      его `token` (сравнить `GET /workflows/{name}` до и после `PUT
      .../code`)
- [ ] Все существующие тесты проходят без изменений; новые тесты покрывают
      [S3]–[S6]
