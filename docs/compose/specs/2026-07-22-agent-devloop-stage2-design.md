# Agent Dev-Loop — Этап 2: система объясняет себя

> [!NOTE]
> Реализация Этапа 2 из `UPGRADE.md`. Закрывает P3, P4 (минимальный объём,
> без библиотеки one-shot примеров).
> Plan: `docs/compose/plans/2026-07-22-agent-devloop-stage2.md` (после этого спека).
> Роль агента на этом этапе всё ещё существующий `admin` (Этап 3 вводит
> отдельную роль) — RBAC не трогаем, все новые ручки read-only на `_RO`.

## [S1] Problem

`GET /tools` (`orchestrator/api/tools.py`) — единственное место, где агент
может получить сигнатуры и докстринги без чтения исходников: `_parse_module`
(`tools.py:21-49`) делает статический AST-разбор `.py`-файла (без импорта) и
возвращает по каждому классу `{name, docstring, constructor, methods:
[{name, signature, docstring}]}`.

1. **Actions не описаны.** `GET /actions` (`actions.py:41-53`) возвращает
   только список имён файлов. `GET /actions/{name}` и
   `GET /actions/{name}/code` (`actions.py:73-90`) — оба возвращают сырой
   исходник целиком (`{"name": name, "content": content}`, буквально
   дублируют друг друга). Чтобы узнать сигнатуру и докстринг функции-экшена,
   агенту нужно прочитать и распарсить весь файл самому.

2. **Connectors не описаны.** `GET /connectors` и `GET /connectors/{name}`
   (`connectors.py:80-108`, `264-283`) возвращают только
   `{name, class_name, has_code, has_config}` — `class_name` достаётся
   regex'ом `_parse_class_name` (`connectors.py:71-73`), без методов и
   докстрингов. Чтобы узнать, какие методы есть у коннектора (при 25+
   встроенных коннекторах), агенту нужно читать `.py` целиком — самая
   дорогая по контексту операция среди всех сущностей.

3. **Workflow meta не содержит докстринг класса.** `WorkflowRegistry.list()`
   (`soar/workflows/__init__.py:82-93`) уже импортирует классы (для
   регистрации) и собирает `{name, type, schedule, interval, path, token}`
   — докстринг класса рядом, но не читается. `GET /workflows` и
   `GET /workflows/{name}` (`workflows.py:81-120`) отдают то же
   подмножество полей без докстринга.

4. **Нет "как работать с SOAR" одним вызовом.** Кроме `/tools` и одного
   `*_TEMPLATE`-шаблона кода на тип сущности (`actions.py:29-34`,
   `connectors.py:47-63`, `workflows.py:23-60`), у агента нет системного
   промпта (архитектура, конвенции, dev-loop из Этапа 1) и нет места для
   пользовательского промпта (специфичные для инсталляции инструкции,
   задаваемые оператором).

## [S2] Solution overview

Три расширения, переиспользующие уже работающие механизмы — ни одно не
меняет модель исполнения:

1. **Общий модуль интроспекции** ([S3]) — `_parse_module` из `tools.py`
   выносится в `orchestrator/core/introspect.py` как `parse_classes()` (то
   же поведение, просто общее место), плюс новая `parse_functions()` для
   top-level функций (нужна для actions). `tools.py` переключается на
   импорт вместо локальной копии.
2. **`GET .../describe` для actions и connectors** ([S4]) — новые read-only
   ручки на существующих `_RO`, использующие [S3]; `GET /actions`/
   `GET /connectors` (list) получают поле `summary` (первая строка
   докстринга), как уже делает `GET /tools`.
3. **Докстринг в workflow meta** ([S5]) — одна новая пара строк в
   `WorkflowRegistry.list()` + проброс поля через `WorkflowMeta` до
   `GET /workflows`/`GET /workflows/{name}`.
4. **Системный + пользовательский промпт** ([S6]) — системный: статический
   `.md`-файл внутри `orchestrator/` (копируется в образ вместе с кодом,
   см. обоснование пути ниже), отдаётся новой read-only ручкой.
   Пользовательский: файл в data-репозитории (`git.workflows_repo`),
   CRUD+git — тот же паттерн admin-write/`_RO`-read, что уже есть для
   actions/workflows/connectors.

## [S3] Общий модуль интроспекции

Новый `orchestrator/core/introspect.py`:

```python
import ast
from pathlib import Path


def _signature(fn: ast.FunctionDef) -> str:
    args = [a.arg for a in fn.args.args if a.arg != "self"]
    return f"({', '.join(args)})"


def _summary(docstring: str) -> str:
    return docstring.splitlines()[0] if docstring else ""


def parse_classes(path: Path) -> list[dict]:
    """Static AST parse of a module's top-level classes — never imports it.
    Moved from orchestrator/api/tools.py without behavior change."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        methods = [
            {"name": item.name, "signature": _signature(item), "docstring": ast.get_docstring(item) or ""}
            for item in node.body
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
        ]
        init = next(
            (n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None,
        )
        classes.append({
            "name": node.name,
            "docstring": ast.get_docstring(node) or "",
            "constructor": _signature(init) if init else "()",
            "methods": methods,
        })
    return classes


def parse_functions(path: Path) -> list[dict]:
    """Static AST parse of a module's top-level functions — never imports it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        {"name": node.name, "signature": _signature(node), "docstring": ast.get_docstring(node) or ""}
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]
```

`orchestrator/api/tools.py` — удалить локальные `_signature`/`_summary`/
`_parse_module`, импортировать `parse_classes`/`_summary`
(`_summary` тоже переезжает в `introspect.py`, `tools.py` его импортирует)
из `orchestrator.core.introspect`. Поведение и формат ответа `GET /tools`,
`GET /tools/{name}` не меняются — чисто перенос кода, покрыт существующими
тестами `tests/orchestrator/api/test_tools_api.py`.

## [S4] P3 — describe для actions и connectors

**Actions** (`orchestrator/api/actions.py`):

- `GET /actions` — для каждого файла вызвать `parse_functions(path)`,
  найти функцию с именем файла (`ActionsRegistry` ищет по имени файла, не
  по имени функции первой в файле — сохранить это правило), добавить
  `"summary": _summary(fn["docstring"])` в элемент списка (`""`, если
  функция не найдена или файл не парсится — не 500).
- Новая `GET /actions/{name}/describe`, `_RO`:
  ```python
  @router.get("/{name}/describe", dependencies=[Depends(require_role(*_RO))])
  async def describe_action(name: str, request: Request):
      validate_name(name)
      config = request.app.state.config
      filepath = os.path.join(config.soar.actions_dir, f"{name}.py")
      validate_path_within(config.soar.actions_dir, filepath)
      if not os.path.exists(filepath):
          raise HTTPException(status_code=404, detail="Action not found")
      for fn in parse_functions(Path(filepath)):
          if fn["name"] == name:
              return {**fn, "module": name}
      raise HTTPException(status_code=404, detail=f"No function named '{name}' found in {name}.py")
  ```

**Connectors** (`orchestrator/api/connectors.py`):

- `GET /connectors` / `GET /connectors/{name}` — если `has_code`, добавить
  `"summary"` из докстринга класса, найденного через `parse_classes` (по
  `class_name`, уже извлекаемому `_parse_class_name`); `""` при ошибке
  парсинга (сохраняет текущее поведение try/except вокруг чтения файла).
- Новая `GET /connectors/{name}/describe`, `_RO`:
  ```python
  @router.get("/{name}/describe", dependencies=[Depends(require_role(*_RO))])
  async def describe_connector(name: str, request: Request):
      validate_name(name)
      config = request.app.state.config
      filepath = os.path.join(config.soar.connectors_dir, name, f"{name}.py")
      validate_path_within(config.soar.connectors_dir, filepath)
      if not os.path.exists(filepath):
          raise HTTPException(status_code=404, detail="Connector not found")
      classes = parse_classes(Path(filepath))
      class_name = _parse_class_name(Path(filepath).read_text(encoding="utf-8"))
      for cls in classes:
          if cls["name"] == class_name:
              return {**cls, "module": name}
      raise HTTPException(status_code=404, detail=f"No class '{class_name}' found in {name}.py")
  ```

Обе ручки — только код (`.py`), конфиг коннектора (`.yml`) вне
интроспекции, как и в текущем `get_connector_config`.

**Ограничение (наследуется от `parse_classes`/`_parse_class_name`, как и
в текущем `/tools`):** класс должен наследоваться напрямую по имени
(`class X(BaseConnector)`), алиасы импорта (`as BC`) не распознаются —
тот же компромисс, что уже принят для [S3 stage 1] `validate_connector_code`.

## [S5] P3 — докстринг workflow в meta

`soar/workflows/__init__.py::WorkflowRegistry.list()` — добавить одну
строку после `meta = {"name": name, "type": cls.workflow_type}`:

```python
meta["docstring"] = cls.__doc__ or ""
```

Классы уже импортированы в процессе на момент вызова `list()` (см. риск
P5, не расширяется этим изменением — не добавляет новый импорт, только
читает атрибут уже импортированного класса).

`orchestrator/models/workflow_meta.py::WorkflowMeta` — добавить поле:

```python
docstring: str = ""
```

`orchestrator/main.py::load_workflow_metas` — передать
`docstring=wf_info.get("docstring", "")` в конструктор `WorkflowMeta`.

`orchestrator/api/workflows.py::list_workflows`/`get_workflow` — добавить
`"docstring": m.docstring`/`"docstring": meta.docstring` в собираемый
словарь (оба места, строки ~86-98 и ~108-119).

Workflow, зарегистрированные только через `orchestrator_state.yaml` (ветка
"for name, saved in state_workflows.items(): ... if not in soar_metas" в
`load_workflow_metas`, строки ~127-134 — сущность есть в состоянии, но не
в реестре, т.е. файл удалён/не импортируется) — `docstring` остаётся `""`
по умолчанию поля.

## [S6] P4 — системный и пользовательский промпт

**Расположение системного промпта.** `orchestrator/Dockerfile` (локальная
разработка) делает `COPY . .` — любой путь в репозитории работает. Но
`deploy/prod/Dockerfile.orchestrator` и `deploy/stage/Dockerfile.orchestrator`
копируют только `soar/`, `orchestrator/`, `alembic/`, `alembic.ini`
поточечно — `docs/` **не попадает в образ**. Файл должен лежать внутри
`orchestrator/`, иначе "версионируется вместе с кодом" на проде не
выполняется. Решение: `orchestrator/prompts/system_prompt.md`.

`orchestrator/config.py::SoarConfig` — новое поле, по аналогии с
`tools_dir: str = "soar/tools"` (тоже relative-to-cwd default):

```python
system_prompt_path: str = "orchestrator/prompts/system_prompt.md"
```

Новый роутер `orchestrator/api/prompts.py`:

```python
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser, require_role
from orchestrator.db.session import get_db

router = APIRouter(prefix="/prompts", tags=["prompts"])
_RO = ("viewer", "analyst", "service", "admin")
_ADMIN = ("admin",)


class UserPromptRequest(BaseModel):
    content: str


@router.get("/system", dependencies=[Depends(require_role(*_RO))])
async def get_system_prompt(request: Request):
    path = Path(request.app.state.config.soar.system_prompt_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="System prompt not configured")
    return {"content": path.read_text(encoding="utf-8")}


def _user_prompt_path(config) -> Path:
    return Path(config.git.workflows_repo) / "prompts" / "user_prompt.md"


@router.get("/user", dependencies=[Depends(require_role(*_RO))])
async def get_user_prompt(request: Request):
    path = _user_prompt_path(request.app.state.config)
    if not path.exists():
        return {"content": None}
    return {"content": path.read_text(encoding="utf-8")}


@router.put("/user")
async def save_user_prompt(
    request: Request, body: UserPromptRequest,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    config = request.app.state.config
    path = _user_prompt_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content, encoding="utf-8")
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    try:
        commit_hash = await git.commit(
            "prompts/user_prompt.md", "Update user prompt",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    await audit_service.record(
        db, user=user, action="prompt.update_user", resource_type="prompt",
        resource_id="user", request=request, detail={"commit": commit_hash},
    )
    return {"status": "saved", "commit": commit_hash}
```

Зарегистрировать `prompts_router` в `orchestrator/main.py` рядом с
остальными роутерами (`app.include_router(prompts_router)`), добавить в
`orchestrator/api/__init__.py` экспорт по аналогии с `tools_router`.

**Почему без history/diff/restore:** в отличие от кода workflow/action/
connector, ошибка в промпте не ломает регистрацию сущности и не требует
экстренного отката по тому же сценарию, что оправдал [S5 stage1] — MVP-объём
по формулировке `UPGRADE.md` требует только read+write. Если понадобится —
`orchestrator/core/history.py` уже готов принять `git.workflows_repo`-путь
`prompts/user_prompt.md` без изменений, это дополнение тривиально
добавить позже.

**Содержание `orchestrator/prompts/system_prompt.md`** (первая версия,
дальше редактируется как обычный файл в репозитории, не через API):
конспект того, что агенту нужно знать, чтобы работать с SOAR через API, не
читая исходники — структура:

1. Что такое SOAR (детерминированные workflow на ECS, без LLM в самом
   движке — контекст из `CLAUDE.md`).
2. Три типа сущностей и их контракт: `action` (функция, имя = имя файла),
   `connector` (класс-наследник `BaseConnector`), `workflow`
   (класс-наследник `BaseWorkflow`/`ScheduledWorkflow`/`WebhookWorkflow`/
   `ManualWorkflow`, ключ реестра = имя файла, не класса).
3. Dev-loop из Этапа 1: `PUT .../code` → `422` с текстом ошибки при
   невалидном коде вместо тихого успеха; `GET /jobs/{id}` →
   `result_error` с полным traceback; `GET .../history`,
   `GET .../history/{commit}`, `GET .../diff?a=&b=`,
   `POST .../restore` для отката.
4. Самоописание из Этапа 2: `GET /tools`, `GET /actions/{name}/describe`,
   `GET /connectors/{name}/describe`, докстринг в `GET /workflows/{name}`
   — использовать вместо чтения исходников.
5. Конвенции: `context["dry_run"] = True` в `POST /jobs` пропускает
   мутации; `_ensure_connected()` — ленивая инициализация коннектора;
   webhook-токен стабилен между правками кода (Этап 1, P9).
6. Известные ограничения, которые агенту стоит знать заранее: секреты
   коннектора отдаются в открытом виде (P6, риск), нет блокировки
   параллельного редактирования (P10, риск) — не полагаться на atomic
   read-modify-write через API.

Точный текст — предмет реализации (пишется вместе с кодом, не заранее в
спеке), но обязан покрывать все 6 пунктов выше.

## [S7] Testing strategy

- `tests/orchestrator/core/test_introspect.py` (новый) — `parse_classes`/
  `parse_functions` на фикстурных `.py`-строках: класс с методами,
  функция с докстрингом, пустой файл, файл с синтаксической ошибкой
  (должен поднимать `SyntaxError`, роут ловит).
- `tests/orchestrator/api/test_tools_api.py` — без изменений в ожиданиях
  (регрессия на перенос кода в [S3]), прогнать как есть.
- `tests/orchestrator/api/test_actions_api.py` — новые случаи:
  `GET /actions` содержит `summary`; `GET /actions/{name}/describe` →
  `{name, signature, docstring, module}` для валидного action; `404` для
  несуществующего; `404` (не 500) для файла, где функция переименована
  (не совпадает с именем файла).
- `tests/orchestrator/api/test_connectors_api.py` — аналогично для
  `describe`: сигнатуры методов, `constructor`, докстринг класса; `404`
  для коннектора без `.py`.
- `tests/soar/test_workflows.py` — `WorkflowRegistry.list()` возвращает
  `docstring` класса; `""` если докстринга нет.
- `tests/orchestrator/api/test_workflows_api.py` — `GET /workflows`/
  `GET /workflows/{name}` включают `docstring`.
- Новый `tests/orchestrator/api/test_prompts_api.py` — `GET /prompts/system`
  читает файл из `config.soar.system_prompt_path` (подменить путь на
  временный файл в фикстуре), `404` если файла нет; `GET /prompts/user`
  → `{"content": null}` если файла нет, содержимое после `PUT`; `PUT
  /prompts/user` требует `_ADMIN` (403 для viewer/analyst/service), делает
  git-commit, пишет `AuditLog`.
- Проверить непустой `orchestrator/prompts/system_prompt.md` реально
  существует в репозитории (не только в тестовой фикстуре) —
  `GET /prompts/system` на dev-сервере должен возвращать реальный контент.

```bash
python -m pytest tests/orchestrator/ tests/soar/ -v
ruff check orchestrator/ soar/
```

## [S8] Non-goals

- **Библиотека one-shot примеров** — явно исключена из Этапа 2 в
  `UPGRADE.md`, не проектируется.
- **P7 (роль агента)** — Этап 3, все новые ручки в [S4]/[S6] используют
  существующие `_RO`/`_ADMIN`.
- **История/diff/restore для промптов** — см. обоснование в [S6]; не
  добавляется, но не блокируется на будущее.
- **Кэширование интроспекции** — `parse_classes`/`parse_functions` читают
  файл с диска на каждый запрос, как уже делает `/tools`; не оптимизируем
  без измеренной проблемы производительности.

## [S9] Success criteria

- [ ] `GET /actions/{name}/describe` и `GET /connectors/{name}/describe`
      возвращают сигнатуры и докстринги без чтения исходников агентом
- [ ] `GET /actions`, `GET /connectors` включают `summary` (первая строка
      докстринга) в элементах списка
- [ ] `GET /workflows`, `GET /workflows/{name}` включают `docstring`
      класса workflow
- [ ] `GET /prompts/system` отдаёт непустой встроенный системный промпт
      одним вызовом, без аутентификации сверх обычного `_RO`
- [ ] `GET /prompts/user` отдаёт `null`/пусто по умолчанию, `PUT
      /prompts/user` (admin) сохраняет с git-коммитом и audit-записью
- [ ] `GET /tools` не меняет поведение после переноса в
      `core/introspect.py`
- [ ] Все существующие тесты проходят без изменений; новые тесты
      покрывают [S3]–[S6]
