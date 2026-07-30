# Модель сущностей в коде — Phase 2 (E6+E3 одним заходом, E8, dry-run, audit trail, E7, E5, http_client migration)

> Реализует Фазу 2 из `docs/concepts/ENTITY-MODEL.md`. Зависит от Фазы 1
> (`docs/compose/specs/2026-07-30-runtime-boundary-design.md`) —
> контентный venv должен существовать до того, как прокси начнёт логировать
> вызовы в лог джобы, который парсит оркестратор. Один спек на все пункты
> фазы 2, т.к. решение 4 требует E6 (прямой импорт) и E3 (прокси) одним
> заходом: если шим отдаёт сырой объект коннектора до появления прокси,
> прямой импорт становится дырой в обход прокси в момент его внедрения.

## [S1] Problem

Пять независимых дефектов, растущих из того, что импорт коннектора и его
логирование никогда не проектировались как одна граница:

1. **E6.** Реальный доступ к коннектору — `connectors.vt_main.get_ip_report(ip)`
   через `__getattr__` реестра (`soar/connectors/__init__.py:121`).
   Концептная форма `from soar.connectors.virus_total import vt_main`
   нигде не встречается. Опечатка в имени инстанса — `AttributeError` в
   рантайме джобы, а не ошибка импорта, которую ловят
   `validate_workflow_code`/mypy/IDE. Порядок инициализации в
   `soar/runner.py` (`workflows.init()` раньше `connectors.init()`) молча
   роняет воркфлоу с прямым импортом из реестра — сегодня не проявляется,
   потому что прямого импорта никто не пишет.
2. **E3.** Единая точка логирования (`http_client`) используют 3
   коннектора из 24. 7 ходят через голый `requests`/`httpx`. Остальные —
   через SDK/протокольные клиенты (`paramiko`, `ldap3`, `pymssql`), где
   HTTP-слой неприменим в принципе — и именно они делают самые опасные
   вещи. `BaseConnector` логирует только `connect`/`disconnect`, не вызовы
   методов. `audit.service.record` не видит ничего из того, что джоба
   сделала во внешней системе.
3. **E8.** `self._configs[instance_name]` (`soar/connectors/__init__.py:57`)
   — плоское пространство имён без учёта типа коннектора. Два коннектора
   разных типов с инстансом `prod` — зарегистрирован только последний.
   `_discover_classes`/`_discover_external` берут **любой** найденный
   `BaseConnector`-подкласс из `dir(mod)` без проверки `obj.__module__ ==
   fqn` (в отличие от `WorkflowRegistry._discover`, где эта проверка уже
   есть) — импорт одним коннектором другого перезапишет первый.
4. **Dry-run** — `context["dry_run"]` читает сам воркфлоу добровольно.
   Для чужого контента это не гарантия.
5. **E7.** Регистрируется только callable с именем == имени файла
   (`soar/actions/__init__.py:28`). `GET /actions` листит файлы с диска
   (`orchestrator/api/actions.py:51`) — независимо от реестра, поэтому
   незарегистрированный экшен выглядит рабочим в UI.
6. **E5.** `GET /tools` — glob по каталогу, отдаёт все top-level классы всех
   файлов (`orchestrator/api/tools.py`) — внутреннюю механику кэша
   (`CacheBackend`/`InMemoryCache`/`RedisCache`), классы вместо синглтонов
   (`HttpClient`/`SyncHttpClient` есть, `http_client`/`http_client_sync`
   нет), и `OpenAPIGenerator`, который вообще не инструмент рантайма —
   единственный потребитель `orchestrator/api/connectors.py`.
   `WatermarkStore`/`SeenStore` не следуют контракту синглтона:
   `http_client` — готов к использованию, `WatermarkStore` поток обязан
   инстанцировать сам с путём к файлу.

## [S2] Solution overview

Порядок реализации внутри фазы (зависимости, не риск):

```
1. Реестр коннекторов: пространство имён по типу + детерминированный выбор
   класса (E8) — фундамент, на котором строится шим.
2. Лениные шимы + прокси одним PR (E6+E3, решение 4).
3. Dry-run на прокси — надстройка над прокси из шага 2, декларация
   MUTATING_METHODS на коннекторах.
4. Аудит вызовов из джобы в AuditLog — читает то, что прокси уже пишет в
   лог джобы (шаг 2), самая дорогая часть фазы.
5. E7 (actions), E5 (tools) — независимы от 1-4, делаются тем же заходом,
   т.к. они часть той же "модель сущностей в коде" фазы, но не блокируют
   и не блокируются шагами 1-4.
6. Миграция оставшихся 7 requests/httpx-коннекторов на http_client_sync —
   гигиена после того, как прокси и аудит-хук уже дают гарантию; дешевле
   сделать в этом заходе, чем оставлять отдельным треком.
```

## [S3] Реестр коннекторов: пространство имён по типу (E8)

`soar/connectors/__init__.py::ConnectorRegistry` — `_connectors`/`_configs`
переходят с плоского `dict[instance_name, ...]` на вложенный
`dict[type_name, dict[instance_name, ...]]`:

```python
class ConnectorRegistry:
    def __init__(self):
        self._connectors: dict[str, dict[str, BaseConnector]] = {}
        self._classes: dict[str, type[BaseConnector]] = {}
        self._configs: dict[str, dict[str, dict]] = {}  # type -> instance -> {params}
```

`_discover_classes`/`_discover_external` — добавить проверку
`obj.__module__ == fqn`, как уже сделано в `WorkflowRegistry._discover`
(`soar/workflows/__init__.py:34`) — детерминированный выбор класса вместо
last-wins по `dir(mod)`:

```python
for attr_name in dir(mod):
    obj = getattr(mod, attr_name)
    if (
        isinstance(obj, type)
        and issubclass(obj, BaseConnector)
        and obj is not BaseConnector
        and obj.__module__ == fqn
    ):
        self._classes[connector_dir.name] = obj
```

`_load_configs_from_dir` — коллизия имени инстанса **внутри одного типа**
(было невозможно отличить от кросс-типовой — теперь можно и нужно) кидает
внятную ошибку вместо молчаливого last-wins:

```python
def _load_configs_from_dir(self, base_dir: Path) -> None:
    for connector_dir in base_dir.iterdir():
        if not connector_dir.is_dir() or connector_dir.name.startswith("_"):
            continue
        type_name = connector_dir.name
        for yml_file in connector_dir.glob("*.yml"):
            if yml_file.name.endswith(".example.yml"):
                continue
            try:
                with open(yml_file) as f:
                    config = yaml.safe_load(f)
                if config and "instances" in config:
                    bucket = self._configs.setdefault(type_name, {})
                    for instance_name, params in config["instances"].items():
                        if instance_name in bucket:
                            _log.warning(
                                f"Duplicate instance '{instance_name}' for "
                                f"connector type '{type_name}' in {yml_file} — "
                                "overwriting previous definition"
                            )
                        bucket[instance_name] = params
            except Exception as e:
                _log.warning(f"Failed to load config {yml_file}: {e}")
```

`init()` строит `self._connectors[type_name][instance_name]` вместо
плоского словаря. `list()` расплющивает обратно для API-совместимости
(`GET /connectors` не меняет форму ответа — `name` остаётся глобально
видимым идентификатором инстанса в UI, только внутреннее хранение меняется):

```python
def list(self) -> list[dict]:
    return [
        {"name": name, "type": type_name, "connected": c.is_connected}
        for type_name, instances in self._connectors.items()
        for name, c in instances.items()
    ]
```

Новый метод, используемый шимом (см. [S4]):

```python
def get_instance(self, type_name: str, instance_name: str) -> BaseConnector | None:
    return self._connectors.get(type_name, {}).get(instance_name)
```

`ConnectorRegistry.__getattr__` (используется существующим кодом,
`connectors.<instance>` без типа) — сохраняется для обратной совместимости
внутри этой фазы **как путь, который тоже должен идти через прокси**, не
только новый `from soar.connectors.<type> import <instance>`. См. [S4] —
`__getattr__` реестра тоже отдаёт `ConnectorProxy`, не сырой объект;
плоский поиск при коллизии имени между типами берёт первый найденный и
логирует warning (переходное поведение внутри этой фазы, не новый баг —
сегодня оно уже недетерминировано при коллизии, после этой правки хотя бы
видимо в логе).

Удалить `soar/connectors/es_http/` — пустой каталог-призрак без единого
`.py` (упомянут в E8 как единственное исключение из "один класс на
каталог").

## [S4] Ленивые шимы + прокси (E6 + E3, решение 4)

**`ConnectorProxy`** — новый класс, `soar/connectors/_proxy.py` (приватный
модуль — не публичная поверхность, только механизм):

```python
"""Обёртка вокруг BaseConnector-инстанса — единственный способ получить
коннектор что через soar.connectors.connectors.<instance>, что через
from soar.connectors.<type> import <instance>. Оба пути — один механизм с
двумя фасадами (docs/concepts/ENTITY-MODEL.md, решение 4): шим никогда не
отдаёт self._instance напрямую, поэтому прямой импорт не может стать дырой
в обход логирования/dry-run, даже если появится позже."""

import functools
import os
import time
from typing import Any

from soar.connectors.base import BaseConnector
from soar.logger import get_logger
from soar.runtime_state import is_dry_run

_log = get_logger("connector.proxy")


class ConnectorProxy:
    def __init__(self, instance: BaseConnector, type_name: str):
        object.__setattr__(self, "_instance", instance)
        object.__setattr__(self, "_type_name", type_name)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._instance, name)
        if name.startswith("_") or not callable(attr):
            return attr
        return self._wrapped(name, attr)

    def __repr__(self) -> str:
        return f"ConnectorProxy({self._type_name}.{self._instance.instance_name})"

    def _wrapped(self, name: str, method):
        hidden = getattr(type(self._instance), "HIDDEN_FIELDS", set())
        mutating = name in getattr(type(self._instance), "MUTATING_METHODS", set())

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            job_id = os.environ.get("SOAR_JOB_ID", "")
            safe_kwargs = {k: ("***" if k in hidden else v) for k, v in kwargs.items()}
            target = f"{self._type_name}.{self._instance.instance_name}.{name}"

            if mutating and is_dry_run():
                _log.bind(audit=True).info(
                    f"SOAR_AUDIT_EVENT connector.call.dry_run target={target} "
                    f"args={args} kwargs={safe_kwargs} job_id={job_id}"
                )
                return None

            start = time.monotonic()
            outcome = "ok"
            try:
                return method(*args, **kwargs)
            except Exception as e:
                outcome = f"error:{type(e).__name__}"
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                _log.bind(audit=True).info(
                    f"SOAR_AUDIT_EVENT connector.call target={target} "
                    f"args={args} kwargs={safe_kwargs} duration_ms={duration_ms} "
                    f"outcome={outcome} job_id={job_id}"
                )
        return wrapper
```

`args`/`kwargs` в лог-строке — позиционные аргументы не редактируются
(коннекторы принимают секреты только как kwargs конструктора, не как
позиционные аргументы методов — проверено по всем 24 сигнатурам; если
находится исключение на этапе плана, соответствующий коннектор переводится
на kwargs, а не логирование учит различать позиции).

`SOAR_AUDIT_EVENT ` — фиксированный текстовый префикс перед человекочитаемой
частью строки, не JSON-блок целиком (в отличие от аудит-хука из Фазы 1,
которому не нужен парсинг человеком) — здесь важно, чтобы оркестратор мог
`grep`-ом выделить строки для парсинга ([S6]), а разработчик — читать
лог джобы глазами без инструмента. Точный формат (что после
`SOAR_AUDIT_EVENT`) — единственное поле, которое парсит [S6]; пары
`key=value` через `str()`, не `repr()`/JSON, чтобы не плодить двойное
экранирование — конкретный regex фиксируется в плане вместе с парсером.

**Новый модуль `soar/runtime_state.py`** — процесс-глобальное состояние на
время одной джобы (один subprocess = одна джоба, см. Runner contract в
`AGENTS.md`):

```python
"""Process-wide state for the current job — one soar.runner subprocess is
always exactly one job (see Runner contract, AGENTS.md), so a module-level
flag is the whole job's dry_run status, not per-call context threading."""

_dry_run = False


def set_dry_run(value: bool) -> None:
    global _dry_run
    _dry_run = value


def is_dry_run() -> bool:
    return _dry_run
```

`soar/runner.py::main()` — `set_dry_run(bool(context.get("dry_run",
False)))` сразу после парсинга `context`, до `workflows.execute(...)`.

**Шимы** — `soar/connectors/__init__.py` получает функцию, вызываемую из
`ConnectorRegistry.init()` после построения `self._connectors`:

```python
import types


def _install_shims(registry: "ConnectorRegistry") -> None:
    for type_name in registry._connectors:
        fqn = f"soar.connectors.{type_name}"

        def _getattr(instance_name: str, _type_name: str = type_name) -> ConnectorProxy:
            inst = registry.get_instance(_type_name, instance_name)
            if inst is None:
                raise AttributeError(
                    f"Connector instance '{instance_name}' of type "
                    f"'{_type_name}' not found"
                )
            return ConnectorProxy(inst, _type_name)

        mod = sys.modules.get(fqn) or types.ModuleType(fqn)
        mod.__getattr__ = _getattr
        sys.modules[fqn] = mod
```

Вызывается из `ConnectorRegistry.init()` последней строкой (после
`_log.info(f"Registered {len(...)} connectors")`). Замена
`sys.modules[fqn]` **безопасна и для встроенных, и для внешних
коннекторов**: для встроенных `soar.connectors.<type>` сегодня — namespace
package (директория без `__init__.py`, PEP 420) или уже созданный
`importlib.import_module` объект из `_discover_classes` — в обоих случаях
перезапись `__getattr__` на существующий module-объект не ломает уже
загруженный класс коннектора (тот остаётся доступен по
`soar.connectors.<type>.<module_name>.<ClassName>`, шим добавляет только
атрибут-резолвер поверх). Для внешних — `fqn` мог не существовать в
`sys.modules` вообще (только `fqn.<module_name>` от `_discover_external`),
создаётся новый `ModuleType`.

`ConnectorRegistry.__getattr__` (плоский путь, [S3]) тоже отдаёт прокси:

```python
def __getattr__(self, name: str) -> "ConnectorProxy":
    if name.startswith("_"):
        raise AttributeError(name)
    for type_name, instances in self._connectors.items():
        if name in instances:
            return ConnectorProxy(instances[name], type_name)
    raise AttributeError(f"Connector '{name}' not found")
```

**Шаблоны воркфлоу/экшенов** (`orchestrator/api/workflows.py::TEMPLATES`,
`orchestrator/api/actions.py::ACTION_TEMPLATE`) — переписать на
концептную форму, теперь что она реально гарантирует прокси:

```python
from soar.connectors.virus_total import vt_main
```

вместо `from soar.connectors import connectors` +
`connectors.vt_main....` — обновить плейсхолдер в шаблонах на
generic-форму `from soar.connectors.<type> import <instance>` с
комментарием-примером (шаблоны не знают, какой тип коннектора реально
настроен у конкретной инсталляции — оставить оба варианта показанными в
комментарии, как сегодня шаблон показывает `connectors.<name>` без
привязки к типу).

## [S5] Dry-run на прокси

`BaseConnector` (`soar/connectors/base.py`) получает
`MUTATING_METHODS: ClassVar[set[str]] = set()` — та же конвенция, что уже
есть для `HIDDEN_FIELDS` (class-level, объявляется каждым коннектором,
читается прокси в рантайме через `getattr(type(...), ...)`). На этапе
плана — пройтись по всем 24 коннекторам и проставить `MUTATING_METHODS` для
методов, реально мутирующих внешнее состояние (`send_email`,
`send_message`, `index`, `exec_command`, `put_file`, `modify`, `create_*`,
`delete_*`, ...) — read-only методы (`get_*`, `search`, `list_*`, `query`
без побочных эффектов) в множество не входят.

Это же поле — будущий источник манифеста пака в Фазе 3 (там же уже указано:
"признаки мутирующих методов (нужны dry-run из фазы 2)") — не заводить
второе объявление, манифест читает `MUTATING_METHODS` через AST (тот же
паттерн, что `_hidden_fields()` в `orchestrator/core/introspect.py`), не
дублирует список руками.

## [S6] Аудит вызовов из джобы → `AuditLog`

Канал уже существует: `Worker._execute` (`orchestrator/core/worker.py:94`)
читает `job.log_path` целиком, чтобы достать последнюю JSON-строку
(`WorkflowResult`). Расширяется тем же чтением — построчный скан на
префикс `SOAR_AUDIT_EVENT `:

```python
# orchestrator/core/audit_parse.py — новый модуль, вызывается из Worker
import re

_EVENT_RE = re.compile(
    r"SOAR_AUDIT_EVENT connector\.call(?:\.(dry_run))? target=(\S+) "
    r"args=(.*?) kwargs=(.*?) (?:duration_ms=(\d+) )?outcome=(\S+ )?job_id=(\S*)$"
)
```

Точный regex/парсер фиксируется в плане вместе с [S4] (одна работа —
формат строки и парсер пишутся и тестируются вместе, чтобы не разойтись).
Результат парсинга — список
`{"target": ..., "outcome": ..., "duration_ms": ..., "dry_run": bool}` без
попытки распарсить `args=`/`kwargs=` обратно в структуры (они и так уже
редактированы прокси; для `AuditLog.detail` достаточно строки как есть —
парсить args/kwargs строже, чем нужно, было бы отдельным риском
инъекции/некорректного разбора произвольных `repr()` пользовательских
объектов).

`orchestrator/audit/service.py` получает вариант `record()` без `Request`
(job-triggered событие не имеет HTTP-запроса):

```python
async def record_job_event(
    db: AsyncSession,
    *,
    job: WorkflowJob,
    action: str,
    resource_id: str,
    detail: dict,
) -> None:
    entry = AuditLog(
        actor_id=0,
        actor_type="service",
        actor_name=f"job:{job.workflow_name}",
        action=action,
        resource_type="connector",
        resource_id=resource_id,
        client_ip=None,
        request_id=None,
        detail=detail,
        created_at=datetime.now(UTC),
    )
    db.add(entry)
    await db.commit()
```

(тот же синтетический-actor паттерн, что уже используется для
`job.create` от вебхука — `AGENTS.md`, "Audit trail" — не новый прецедент).

**Вызывается из `Worker._execute`**, сразу после существующего блока
парсинга `result_data` из последней строки, тем же чтением `lines`.
`Worker` сегодня не держит `db_session_factory` — добавляется как
опциональный конструкторский параметр (используется только для этой
записи; `None` = аудит вызовов джобы выключен, обратная совместимость для
любого места, инстанцирующего `Worker` напрямую без БД, если такое есть —
проверить на этапе плана; сегодня единственный конструктор —
`WorkerPool`, получает `db_session_factory` из `app.state`, прокидывает в
каждый `Worker`).

Экшены (`soar/actions/`), не только коннекторы, могут вызывать
`http_client_sync`/коннекторы — их собственный код не оборачивается
прокси (экшен — не сущность с реестром инстансов, это функция). Аудит
вызовов экшена целиком не в скоупе фазы 2: коннектор внутри экшена уже
даёт трассировку через прокси (что действительно ушло вовне), вызов самого
экшена как таковой — это уже уровень workflow, который логируется
`BaseWorkflow.execute()` (`Starting workflow .../ completed in ...`,
`soar/workflows/base.py:34`).

## [S7] Экшены: несколько экспортов (E7)

`soar/actions/__init__.py::_discover`/`_discover_external` — регистрировать
**все** public top-level callables модуля вместо единственного
совпадающего по имени файла:

```python
def _discover(self) -> None:
    package_dir = Path(__file__).parent
    for _finder, module_name, is_pkg in pkgutil.iter_modules([str(package_dir)]):
        if is_pkg or module_name.startswith("_"):
            continue
        fqn = f"soar.actions.{module_name}"
        try:
            mod = importlib.import_module(fqn)
        except ImportError as e:
            _log.warning(f"Failed to import {fqn}: {e}")
            continue
        found = False
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            obj = getattr(mod, attr_name)
            if callable(obj) and getattr(obj, "__module__", None) == fqn:
                self._actions[attr_name] = obj
                found = True
        if not found:
            _log.warning(f"No public callable in {fqn}")
```

(симметрично для `_discover_external`). Регистрация ключом становится
**имя callable**, не имя файла — коллизия имён между файлами возможна
(два файла экспортируют функцию с одинаковым именем) — last-wins с
warning, тот же паттерн, что уже принят для коннекторов ([S3]).
`getattr(obj, "__module__", None) == fqn` исключает случайно
заимпортированные в модуль чужие callable (тот же класс защиты, что дан
воркфлоу/коннекторам в этой же фазе).

`GET /actions` (`orchestrator/api/actions.py::list_actions`) перестаёт
листить файлы с диска и читает реестр:

```python
@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_actions(request: Request):
    from soar.actions import actions as actions_registry
    actions_dir = request.app.state.config.soar.actions_dir
    actions_registry.init(external_dir=actions_dir)
    return [
        {"name": name, "summary": _describe_action_summary(actions_dir, name)}
        for name in sorted(actions_registry.list())
    ]
```

Открытый вопрос на этапе плана: `list_actions` сегодня — read-only ручка
без стоимости импорта (файлы просто листились). Переход на
`actions_registry.init()` означает **импорт всех экшенов на каждый `GET
/actions`** — тот же trade-off, что уже принят для коннекторов и воркфлоу
(`ConnectorRegistry.init()` тоже импортирует). Обосновано тем, что после
Фазы 1 (контентный venv) сам `orchestrator` процесс **не может** это
делать — импорт экшенов остаётся дозволен только внутри
`soar.runner`-субпроцесса. Значит `GET /actions` не может звать
`actions_registry.init()` из процесса оркестратора **после** Фазы 1 —
до конца Фазы 1 это было бы нарушением только что построенной границы.
**Решение**: `list_actions` использует AST (`parse_functions`, уже
существует в `introspect.py`), не импорт — то же самое, чем сегодня
устроен `_describe_action_summary`, только для перечисления **всех**
public top-level функций/классов файла, а не только одноимённой. Реестр
экшенов (`ActionsRegistry`, реальный импорт) используется исключительно
внутри `soar.runner` при исполнении джобы — `GET /actions` его не трогает
вообще. Итоговая форма:

```python
@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_actions(request: Request):
    actions_dir = request.app.state.config.soar.actions_dir
    if not os.path.exists(actions_dir):
        return []
    result = []
    for entry in sorted(os.scandir(actions_dir), key=lambda e: e.name):
        if entry.name.startswith(("_", ".")) or not entry.name.endswith(".py"):
            continue
        for fn in parse_functions(Path(actions_dir) / entry.name):
            result.append({
                "name": fn["name"],
                "file": entry.name[:-3],
                "summary": _summary(fn["docstring"]),
            })
    return result
```

Это одновременно и исправляет E7 (виден каждый public callable, не только
одноимённый), и не открывает новую дыру в границе рантаймов из Фазы 1.

## [S8] Явная поверхность инструментов (E5)

`soar/tools/__init__.py` объявляет публичный набор explicitly — не через
glob каталога:

```python
from soar.tools.http_client import HttpClient, SyncHttpClient
from soar.tools.watermark import SeenStore, WatermarkStore

http_client = HttpClient()
http_client_sync = SyncHttpClient()

__all__ = ["http_client", "http_client_sync", "WatermarkStore", "SeenStore"]
```

`GET /tools` (`orchestrator/api/tools.py`) читает `__all__` через AST
(не импорт — тот же паттерн, что весь остальной `/tools`/`/actions`/
`/connectors` слой; `soar/tools/__init__.py` — единственный файл, который
парсится целиком, не через glob):

```python
def _public_names(init_path: Path) -> list[str]:
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "__all__":
                return [el.value for el in node.value.elts if isinstance(el, ast.Constant)]
    return []
```

`list_tools`/`get_tool` фильтруют текущий glob-результат по
`_public_names(tools_dir / "__init__.py")` — синглтоны (`http_client`,
`http_client_sync`) добавляются в вывод отдельной веткой (это не классы,
`parse_classes` их не видит; сегодняшний вывод — только классы, значит
поведение "показать `http_client`" — новая ветка, не фильтр существующей):

```python
@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_tools(request: Request):
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    init_file = tools_dir / "__init__.py"
    if not init_file.is_file():
        return []
    public = set(_public_names(init_file))
    result = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        for cls in parse_classes(py_file):
            if cls["name"] in public:
                result.append({"name": cls["name"], "module": py_file.stem, "summary": _summary(cls["docstring"])})
    # синглтоны, объявленные как переменные, не классы — see __all__ minus
    # class names already covered above
    class_names = {r["name"] for r in result}
    for name in public - class_names:
        result.append({"name": name, "module": "__init__", "summary": ""})
    return result
```

`OpenAPIGenerator` (`soar/tools/openapi.py`) переезжает в
`orchestrator/core/openapi_generator.py` — единственный потребитель уже
`orchestrator/api/connectors.py:366`, механизм оркестратора (генерация кода
коннектора из OpenAPI-спеки), не инструмент рантайма воркфлоу. Импорт в
`connectors.py` меняется на новый путь; `soar/tools/openapi.py` удаляется
целиком (не оставлять re-export-заглушку — проект не делает
backwards-compat shims, `CLAUDE.md`).

Кэш-бэкенды (`CacheBackend`/`InMemoryCache`/`RedisCache`,
`soar/tools/http_client.py:27-69`) — остаются в `http_client.py` (уже там,
не в отдельном файле — спека `ENTITY-MODEL.md` предлагала
`soar/tools/_cache.py`, но реального дублирования/масштаба, оправдывающего
разъезд файла, нет: 40 строк, один потребитель, `_`-префикс модуля не
нужен, когда сами классы не экспортируются в `__all__` — они и так не
видны `GET /tools` после этой правки, вынос в отдельный файл не добавляет
ничего, кроме лишнего файла — не делаем).

`WatermarkStore`/`SeenStore` — контракт синглтона, как `http_client`:
поток не должен передавать путь руками. Добавляется фабрика
`soar/tools/watermark.py::watermark_store(name: str) -> WatermarkStore` /
`seen_store(name: str, ttl: int = 86400) -> SeenStore`, вычисляющая путь
из конфига (`config.soar.*_dir`-подобная секция, например
`config.jobs.log_dir`-соседний `state_dir`, точное поле — на этапе плана,
не заводить новый каталог без причины — вероятно переиспользовать
`config.soar.workflows_dir`-соседний общий `data`-каталог оркестратора)
плюс `name` (обычно — имя воркфлоу, который дедуплицирует/держит курсор).
Экспортируется в `soar/tools/__init__.py::__all__` вместо классов
напрямую — но классы `WatermarkStore`/`SeenStore` тоже остаются
экспортированы (для тестов и для тех, кому нужен нестандартный путь) —
`__all__` включает и классы, и фабрики; `GET /tools` показывает оба.

## [S9] Миграция оставшихся `requests`/`httpx`-коннекторов

`censys`, `crtsh`, `fofa`, `freeipa`, `security_onion`, `urlhaus`, `wazuh`
— переводятся на `http_client_sync` тем же паттерном, что уже показан
`abusech`/`rstcloud`/`kaspersky_opentip`
(`docs/compose/specs/2026-07-28-http-client-sync-facade-design.md`, [S4]).
Не переносятся: коннекторы на специализированных SDK
(`virus_total`→`vt`, `shodan`, `pymisp`) — то же обоснование, что в S1
той спеки (потеря SDK-функциональности не оправдана).

## [S10] Testing Strategy

- `tests/soar/test_connector_registry.py` (или дополнение существующего,
  если есть) — namespace по типу: два инстанса `prod` под разными типами
  сосуществуют; коллизия внутри одного типа — warning + last-wins,
  зафиксировано явным тестом; `_discover_classes`/`_discover_external`
  игнорируют `BaseConnector`-подкласс, импортированный из другого модуля
  (regression на "первый коннектор, который импортирует другой коннектор,
  перезаписывает свою регистрацию" — E8 смежный баг)
- `tests/soar/test_connector_proxy.py` — новый файл:
  - `ConnectorProxy.__getattr__` на публичный метод возвращает wrapper,
    не сырой метод; на приватный (`_`-префикс)/не-callable атрибут —
    отдаёт как есть
  - вызов оборачиваемого метода логирует `SOAR_AUDIT_EVENT` через `_log`
    (мокнуть logger, проверить формат строки и наличие `target=`)
  - `HIDDEN_FIELDS` редактируются в kwargs лога, значение реального
    вызова (`method(*args, **kwargs)`) — нет (проверка, что редакция
    только в логе, не в вызове)
  - `MUTATING_METHODS` + `is_dry_run() == True` → метод не вызывается,
    возвращается `None`, лог помечен `dry_run`
  - `MUTATING_METHODS` + `is_dry_run() == False` → метод вызывается
    нормально
  - метод кидает исключение → лог с `outcome=error:<ExcName>`, исключение
    пробрасывается наружу
- `tests/soar/test_runtime_state.py` — `set_dry_run`/`is_dry_run` простой
  round-trip
- `tests/soar/test_connectors_init.py` — regression:
  `from soar.connectors.<built_in_type> import <configured_instance>`
  (использовать реальный тестовый built-in коннектор с тестовым конфигом,
  например `file` — не требует внешних кредов) возвращает `ConnectorProxy`,
  не сырой `BaseConnector`; опечатка в имени инстанса → `AttributeError`
  на **импорте**, не на вызове метода (главный сценарий E6)
- `tests/orchestrator/test_worker_audit_events.py` — новый файл: job.log с
  синтетическими строками `SOAR_AUDIT_EVENT connector.call target=... ...`
  → `Worker._execute` создаёт соответствующие `AuditLog` записи (мокнуть
  `db_session_factory`); job без audit-строк — ноль вызовов `record_job_event`
- `tests/orchestrator/core/test_audit_parse.py` — юнит-тесты regex/парсера
  на реальных примерах строк из [S4] (успех, dry_run, error outcome)
- `tests/soar/test_actions_registry.py` — файл с двумя public функциями
  → обе зарегистрированы под своими именами; приватная (`_`-префикс) —
  нет; функция, импортированная из другого модуля (`__module__ != fqn`)
  — не регистрируется (regression против "экшен, случайно попавший в
  список")
- `tests/orchestrator/api/test_actions_routes.py` — `GET /actions`
  отражает **все** public callables каждого файла (не только
  одноимённый), не импортирует контент (мокнуть/spy, что
  `importlib.import_module` не вызывается на файлы `actions_dir`)
- `tests/orchestrator/api/test_tools_routes.py` — `GET /tools` фильтрует по
  `__all__`; `CacheBackend`/`InMemoryCache`/`RedisCache`/`OpenAPIGenerator`
  отсутствуют в выводе; `http_client`/`http_client_sync` присутствуют как
  записи без класса
- `tests/soar/tools/test_watermark.py` — `watermark_store(name)`/
  `seen_store(name)` вычисляют путь из конфига без ручной передачи; classes
  напрямую — не меняют поведение (regression)
- 7 новых/переписанных `tests/soar/test_{censys,crtsh,fofa,freeipa,
  security_onion,urlhaus,wazuh}_connector.py` — по образцу
  `test_rstcloud_connector.py` из S1-трека http_client_sync
- Полный `tests/soar/test_*_connector.py` (все 24) — прогнать целиком
  после [S3]/[S4], т.к. рефакторинг реестра — это общий код для всех

## [S11] Success Criteria

- [ ] `ConnectorRegistry` хранит инстансы по `(type, instance_name)`;
      коллизия имени инстанса внутри одного типа — явный warning в логе,
      не молчаливый last-wins; коллизия между разными типами больше не
      существует как проблема (закрывает **E8**)
- [ ] `from soar.connectors.<type> import <instance>` работает для
      встроенных и внешних коннекторов, возвращает `ConnectorProxy`;
      опечатка в имени инстанса — `AttributeError` на импорте
      (закрывает **E6**)
- [ ] Нет пути получить сырой `BaseConnector`-инстанс из публичного API —
      ни через шим, ни через `connectors.<name>` (закрывает **E3** вместе
      с следующим пунктом)
- [ ] Каждый публичный вызов метода коннектора (через любой из двух
      фасадов) пишет `SOAR_AUDIT_EVENT` в лог джобы с редакцией
      `HIDDEN_FIELDS`, длительностью и исходом
- [ ] `context["dry_run"]` блокирует вызовы методов, объявленных в
      `MUTATING_METHODS`, централизованно на прокси — не по добровольному
      соглашению воркфлоу
- [ ] `AuditLog` содержит запись на каждый `SOAR_AUDIT_EVENT` из
      завершённой джобы (закрывает часть **E3** про "что джоба сделала во
      внешней системе — не фиксируется")
- [ ] `soar/actions/__init__.py` регистрирует все public top-level
      callables модуля, не только одноимённый; `GET /actions` показывает
      ровно то, что реестр умеет исполнить (закрывает **E7**), не читая
      файлы напрямую и не импортируя контент из процесса оркестратора
- [ ] `soar/tools/__init__.py::__all__` — единственный источник того, что
      видно `GET /tools`; `OpenAPIGenerator` больше не в `soar/tools/`;
      `http_client`/`http_client_sync` видны как готовые синглтоны,
      `WatermarkStore`/`SeenStore` доступны и как классы, и как
      сконфигурированные фабрики (закрывает **E5**)
- [ ] 7 оставшихся `requests`/`httpx`-коннекторов используют
      `http_client_sync`
- [ ] Полный прогон `pytest tests/` зелёный, `ruff check .` без находок
- [ ] `docs/agents/known-limitations.md` пункт 9 (E1 — частично, structural
      фикс всё ещё в Фазе 3, но "правка не применяется" здесь уже не
      актуальна для логирования/dry-run аспекта) — переформулировать по
      факту
