# Убрать IRP-интеграцию; довести движок (tools discovery API) до состояния "агент строит интеграции сам через API"

> [!NOTE]
> Замена предыдущей версии этого файла. Предыдущая версия чинила границы
> `tools/actions/connectors` внутри существующей IRP-интеграции. Решение
> изменилось: вместо починки на месте — убрать IRP-интеграцию целиком
> (она в `enabled: false`/shadow, ничего не production-critical) и
> вложиться в сам движок, чтобы следующую интеграцию (IRP или любую
> другую) строил через API LLM-агент со стороны общего проекта, а не
> руки в этом репозитории.
> Plan: `docs/compose/plans/2026-07-10-remove-irp-tools-api.md` (создать перед началом работы)

## [S1] Problem / Decision

Ревью IRP-интеграции (v0.5.2) вскрыло системную проблему: бизнес-логика
и настройки одной интеграции просочились мимо API-редактируемых
поверхностей (`orchestrator/config.yaml` вместо `connectors/{name}.yml`,
`soar/tools/` вместо `soar/actions/`) — см. предыдущие итерации этого
ревью и правило "Архитектурный принцип: движок vs поведение" в
`AGENTS.md`.

Чинить это точечно внутри уже написанной IRP-интеграции — деньги в
код, который планируется переписывать заново другим актором (LLM-агент
общего проекта, работающий только через API, без доступа к репозиторию
SOAR). Решение: не чинить, а убрать, и потратить усилия на то, что
действительно нужно любой следующей интеграции — сам движок:

1. `soar/tools/` как набор переиспользуемых примитивов, обнаружимых
   через API (без этого агент не узнает, что уже есть, и будет
   писать дедуп/курсоры заново в каждой интеграции)
2. Подтверждённая полнота API `connectors/actions/workflows` для
   постройки интеграции **только через HTTP**, без правки файлов на
   диске мимо API

## [S2] Solution Overview

| # | Что | Действие |
| --- | --- | --- |
| R1 | IRP-интеграция (коннектор, 4 workflow, `tools/irp_*`, конфиг, тесты) | **Удалить** |
| R2 | `soar/tools/` | Оставить только генерик-примитивы (`OpenAPIGenerator`, `WatermarkStore`/`SeenStore`) + read-only discovery API `GET /tools`, `GET /tools/{name}` |
| R3 | API-поверхность `connectors/actions/workflows` | Аудит: подтвердить, что агент может создать/отредактировать/включить/прогнать интеграцию только через существующие эндпоинты — без пробелов |

## [S3] R1 — Удаление IRP-интеграции

### Удалить полностью

```
soar/connectors/irp/                          # irp.py, __init__.py, irp.example.yml
soar/workflows/alert_triage.py
soar/workflows/irp-events.py
soar/workflows/irp_reconcile.py
soar/workflows/respond_basic.py
soar/tools/irp_settings.py
soar/tools/irp_dispatch.py
soar/tools/triage_policy.py
tests/soar/test_irp_connector.py
tests/soar/test_irp_events_workflow.py
tests/soar/test_irp_reconcile.py
tests/soar/test_alert_triage_workflow.py
tests/soar/test_triage_policy.py
```

Реального `soar/connectors/irp/irp.yml` (с секретами) в репозитории
нет — только `.example.yml`, удаляется вместе с директорией.

### Отредактировать (убрать секцию `irp:`)

- `orchestrator/config.yaml` — удалить блок `irp:` (текущие строки 30-52)
- `deploy/stage/config.yaml` — удалить блок `irp:` (текущие строки 30-50)

### Оставить как есть (историческая справка, не продукт)

- `docs/integration/soc-core-integration-contract.md` — контракт с
  внешней системой; пригодится тому, кто (человек или агент) будет
  строить IRP-коннектор заново через API. Код на него больше не
  ссылается — это чистая документация, хранить не вредно.
- `docs/compose/plans/2026-07-05-irp-integration-workflows.md` —
  запись о том, что было сделано и потом откачено; не переписывать
  задним числом (спеки/планы — журнал решений, не текущее состояние).

### После удаления — обновить (в отчёте, не в этой спеке)

- `AGENTS.md`: убрать IRP из списка коннекторов/workflow/API-таблиц,
  добавить запись в Version history о откате (per правило "AGENTS.md
  отражает фактическое состояние — после итерации, не заранее")
- `CLAUDE.md`: убрать ссылку на активную спеку `2026-07-03-...`,
  относящуюся к IRP-багам, если она всё ещё в "Активные спеки"

## [S4] R2 — Tools Discovery API

После R1 в `soar/tools/` остаются только универсальные классы:
`OpenAPIGenerator` (генератор коннектора из OpenAPI-спеки — то, чем
агент реально будет пользоваться для создания новых коннекторов) и
`WatermarkStore`/`SeenStore` (durable курсор / TTL-дедуп — пригодится
для любой будущей webhook/polling-интеграции, не только IRP).

Задача: сделать эти классы обнаружимыми через API, без чтения
исходников — критично именно потому, что следующим "разработчиком
триажа" будет LLM-агент без доступа к файловой системе репозитория,
только к HTTP API оркестратора.

**Не через импорт** — как и `list_connectors`/`get_connector_code` в
`orchestrator/api/connectors.py` (парсят исходники regex'ом, не
импортируют модуль), `GET /tools` статически парсит `soar/tools/*.py`
через `ast`, чтобы orchestrator-процесс не тянул рантайм-зависимости
произвольного tools-модуля только ради листинга.

```python
# orchestrator/api/tools.py
import ast
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from orchestrator.auth.dependencies import require_role

router = APIRouter(prefix="/tools", tags=["tools"])
_RO = ("viewer", "analyst", "service", "admin")


def _signature(fn: ast.FunctionDef) -> str:
    args = [a.arg for a in fn.args.args if a.arg != "self"]
    return f"({', '.join(args)})"


def _parse_module(path: Path) -> list[dict]:
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
        init = next((n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
        classes.append({
            "name": node.name,
            "docstring": ast.get_docstring(node) or "",
            "constructor": _signature(init) if init else "()",
            "methods": methods,
        })
    return classes


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_tools(request: Request):
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    result = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        for cls in _parse_module(py_file):
            result.append({
                "name": cls["name"], "module": py_file.stem,
                "summary": cls["docstring"].splitlines()[0] if cls["docstring"] else "",
            })
    return result


@router.get("/{name}", dependencies=[Depends(require_role(*_RO))])
async def get_tool(name: str, request: Request):
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    for py_file in tools_dir.glob("*.py"):
        for cls in _parse_module(py_file):
            if cls["name"] == name:
                return {**cls, "module": py_file.stem}
    raise HTTPException(status_code=404, detail="Tool not found")
```

Без `PUT`/`DELETE` — по правилу `AGENTS.md`: `tools/` не редактируется
через API, это часть движка, а не поведение.

### Конфиг

```python
# orchestrator/config.py — SoarConfig
class SoarConfig(BaseModel):
    workflows_dir: str = "/app/data/workflows"
    connectors_dir: str = "/app/data/connectors"
    actions_dir: str = "/app/data/actions"
    tools_dir: str = "soar/tools"    # NEW — встроенный пакет, не per-deployment volume
```

### Пример ответа

```
GET /tools
[
  {"name": "OpenAPIGenerator", "module": "openapi", "summary": "Parse OpenAPI spec and generate SOAR connector code."},
  {"name": "WatermarkStore", "module": "watermark", "summary": "Key → ISO-8601 UTC timestamp of the last processed event."},
  {"name": "SeenStore", "module": "watermark", "summary": "Durable \"already seen\" marks with TTL — dedup between..."}
]

GET /tools/WatermarkStore
{
  "name": "WatermarkStore", "module": "watermark",
  "docstring": "Key → ISO-8601 UTC timestamp of the last processed event...",
  "constructor": "(path)",
  "methods": [
    {"name": "get", "signature": "(key)", "docstring": ""},
    {"name": "set", "signature": "(key, ts)", "docstring": ""}
  ]
}
```

Регистрируется в `orchestrator/api/__init__.py` рядом с остальными
роутерами (`tools_router`).

## [S5] R3 — Аудит API-поверхности для агентской постройки интеграций

Цель: LLM-агент со стороны общего проекта должен суметь создать
коннектор + actions + workflow + включить его + прогнать job —
**только HTTP-запросами** к оркестратору, не трогая файлы/git напрямую.
Проверка по фактическому `orchestrator/api/*.py`:

| Шаг | Эндпоинт | Есть? |
| --- | --- | --- |
| Узнать, что уже есть | `GET /connectors`, `GET /actions`, `GET /workflows`, `GET /tools` | ✓ (`/tools` — NEW, R2) |
| Сгенерировать коннектор из спеки | `POST /connectors/generate`, `POST /connectors/preview` | ✓ |
| Создать коннектор с нуля | `POST /connectors/{name}`, `GET /connectors/template` | ✓ |
| Отредактировать код/конфиг коннектора | `PUT /connectors/{name}/code`, `PUT /connectors/{name}/config` | ✓ |
| Создать/отредактировать action | `PUT /actions/{name}`, `GET /actions/template` | ✓ |
| Создать/отредактировать workflow | `PUT /workflows/{name}/code`, `GET /workflows/code/template` | ✓ |
| Включить workflow | `POST /workflows/{name}/enable` | ✓ |
| Прогнать и проверить | `POST /jobs`, `GET /jobs/{id}` | ✓ |
| Узнать сигнатуры переиспользуемых примитивов | `GET /tools/{name}` | ✓ (NEW, R2) |

Пробелов, кроме `/tools`, не найдено — R2 закрывает единственный
недостающий кусок. Дополнительных изменений в `connectors.py`/`actions.py`/
`workflows.py` в рамках этой спеки не требуется.

## [S6] Out of scope

- Ничего не переносится из удаляемой IRP-интеграции "на будущее" —
  если она понадобится снова, её строит агент через API с нуля,
  используя `docs/integration/soc-core-integration-contract.md` как
  референс контракта
- `CachedHttpClient` (v0.6 roadmap) — отдельная задача, не блокируется
  и не требуется этой спекой
- Аутентификация/роли для агента — уже есть RBAC (`admin`/`analyst`/...),
  вопрос выдачи токена агенту — отдельная организационная задача, не техническая

## [S7] Testing Strategy

- Удаление: `python -m pytest tests/soar/ tests/orchestrator/ -v` —
  после удаления файлов не должно остаться сломанных импортов
  (`grep -r "soar.tools.irp\|soar.connectors.irp\|alert_triage\|irp_reconcile\|irp-events\|respond_basic"`
  по `soar/` и `tests/` — пусто)
- `orchestrator/api/tools.py`:
  - `GET /tools` находит `OpenAPIGenerator`, `WatermarkStore`, `SeenStore`
  - `GET /tools/{unknown}` → 404
  - `_parse_module` не импортирует файл — тест с fixture-модулем,
    содержащим заведомо недоступный `import`, должен парситься без ошибки
  - RBAC: viewer/analyst/service/admin — 200; без токена (если auth
    включена) — 401
- `ConnectorRegistry.init()` без `soar/connectors/irp/` — не падает,
  остальные коннекторы регистрируются как раньше

```bash
python -m pytest tests/ -v
ruff check soar/ orchestrator/
```

## [S8] Rollback / Migration note

Всё в git — `git log` содержит полную историю реализации IRP-интеграции
(`a9441ef`, `9e06af0`, и связанные коммиты). Откат — не потеря знания:
контракт (`docs/integration/soc-core-integration-contract.md`) и
история коммитов остаются источником для повторной постройки. Ничего
из удаляемого не находится в production (`enabled: false`, shadow-режим
обязателен по контракту до cutover) — удаление безопасно.

## [S9] Success Criteria

- `soar/connectors/irp/`, 4 IRP-workflow, `soar/tools/irp_*.py`,
  `soar/tools/triage_policy.py` удалены; связанные тесты удалены
- `orchestrator/config.yaml`, `deploy/stage/config.yaml` не содержат `irp:`
- `soar/tools/` содержит только `openapi.py`, `watermark.py`
- `GET /tools`, `GET /tools/{name}` работают, без импорта модулей,
  без PUT/DELETE
- Полный прогон тестов зелёный, `ruff check` чист
- Нет ни одного `grep`-совпадения на `irp` в `soar/` (кроме, если
  оставлены, комментариев с историческим контекстом — избегать и их)
