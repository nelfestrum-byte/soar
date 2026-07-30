# Runtime Boundary — Phase 1 модели сущностей (content venv, dependency contract, AST workflow metadata, audit hook, GET /runtime)

> Реализует Фазу 1 из `docs/concepts/ENTITY-MODEL.md`: контентный venv
> (решение 3), контракт зависимостей (решение 1), AST-метаданные воркфлоу
> (закрывает E10.3), аудит-хук (решение 2, слой 2), `GET /runtime`
> (закрывает E9). Один спек на все пять пунктов — как явно указано в
> `ENTITY-MODEL.md`, они образуют одну зависимую цепочку: `GET /runtime` без
> контентного venv показал бы не то окружение, а AST-метаданные без
> контентного venv — не улучшение, а условие работоспособности (после
> разделения рантаймов оркестратор физически не сможет импортировать
> воркфлоу, тянущий пакет из контентного контракта).

## [S1] Problem

Сегодня `SubprocessRunner` (`orchestrator/core/subprocess_runner.py:40`)
запускает `sys.executable -m soar.runner` — тот же интерпретатор и те же
site-packages, что у самого оркестратора (FastAPI, SQLAlchemy, asyncpg,
alembic, python-jose, bcrypt, redis). Пять независимых проблем растут из
одного корня — общий рантайм:

1. **Нет физической границы между платформой и контентом** (E10). Контент
   может импортировать `asyncpg`/`alembic`/`jose`, хотя это не имеет
   отношения к его задаче — граница живёт только в голове автора.
2. **Зависимости коннекторов не установлены** (E2). `soar/requirements.txt`
   не устанавливается нигде; Dockerfile ставит только
   `orchestrator/requirements.txt` плюс `elasticsearch vt-py requests httpx`
   руками. 11 из 24 коннекторов не хватает пакетов, `_discover_classes`
   ловит `ImportError` и молча роняет коннектор из реестра.
3. **`load_workflow_metas`** (`orchestrator/main.py:108`) вызывает
   `wf_registry.init()`, который **импортирует** каждый файл в
   `workflows_dir` — top-level код чужого модуля выполняется в
   привилегированном процессе оркестратора на каждый reload (E10.3).
4. **Окружение исполнения не описано по API** (E9). Узнать, что можно
   импортировать в коннекторе, нельзя ниоткуда, кроме исходников и хоста —
   `soar/requirements.txt` не отражает реальность (см. п.2), Dockerfile
   недоступен по API.
5. Как следствие всего этого, `docker exec` / чтение `requirements.txt` /
   поход к админу — единственные способы ответить на вопрос "что мне
   доступно" (принцип 4, `AGENTS.md`).

## [S2] Solution overview

Порядок зависимостей внутри фазы (соблюдать при реализации):

```
контентный venv (решение 3)
   └─ контракт зависимостей (решение 1) — что именно ставится в venv
        └─ GET /runtime (E9) — интроспектирует venv, отдаёт по контракту
AST-метаданные воркфлоу (E10.3) — независим по коду, но без контентного
   venv не был бы обязателен: оркестратор мог бы продолжать импортировать,
   просто рискованно. После разделения рантаймов импорт воркфлоу, тянущего
   пакет только из контентного контракта, в процессе оркестратора упадёт
   ImportError — то есть AST-метаданные становятся условием работоспособности,
   не только гигиеной.
аудит-хук (решение 2, слой 2) — независим от остальных, ставится в
   soar/runner.py, который уже существует; помещён в эту фазу, т.к. решение
   2 требует его наличия раньше первого init() контента, а soar/runner.py
   правится тем же заходом, что и подключение контентного venv.
```

## [S3] Контентный venv (решение 3)

**Два venv в образе вместо одного системного python:**

- `/app/platform-venv` — `orchestrator/requirements.txt` (FastAPI,
  SQLAlchemy, asyncpg, alembic, python-jose, bcrypt, redis, ...). На него
  ссылается `uvicorn`, весь код `orchestrator/`.
- `/app/content-venv` — `soar/requirements.txt` (контракт из [S4]). На него
  ссылается **только** `SubprocessRunner`, ничего внутри `orchestrator/` его
  не импортирует и не читает как site-packages.

`deploy/{prod,stage}/Dockerfile.orchestrator` (сегодня — один
`pip install -r orchestrator/requirements.txt elasticsearch vt-py requests
httpx`, п. `soar/requirements.txt` не участвует вообще):

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN groupadd -r soar && useradd -r -g soar -d /app -s /sbin/nologin soar

WORKDIR /app

COPY soar/ /app/soar/
COPY orchestrator/ /app/orchestrator/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Platform venv — оркестратор и всё, от чего он зависит. Первый на PATH,
# поэтому голые `python`/`pip`/`alembic` (soarctl, docker exec) резолвятся
# сюда — поведение снаружи не меняется.
RUN python -m venv /app/platform-venv && \
    /app/platform-venv/bin/pip install --no-cache-dir -r /app/orchestrator/requirements.txt
ENV PATH="/app/platform-venv/bin:${PATH}"

# Content venv — soar/ + контракт зависимостей ([S4]). НЕ на PATH: граница
# зависимостей физическая, а не "не забыть отдельно активировать" — см.
# docs/concepts/ENTITY-MODEL.md, решение 3.
RUN python -m venv /app/content-venv && \
    /app/content-venv/bin/pip install --no-cache-dir -r /app/soar/requirements.txt

RUN mkdir -p /app/data /app/data/workflows /app/data/actions /app/data/connectors /var/log/soar/jobs && \
    find /app/soar/workflows -maxdepth 1 -name '*.py' ! -name '__init__.py' ! -name 'base.py' -exec cp -n {} /app/data/workflows/ \; 2>/dev/null || true && \
    find /app/soar/actions -maxdepth 1 -name '*.py' ! -name '__init__.py' -exec cp -n {} /app/data/actions/ \; 2>/dev/null || true && \
    find /app/soar/connectors -maxdepth 1 -mindepth 1 -type d ! -name '__pycache__' ! -name '_*' -exec cp -rn {} /app/data/connectors/ \; 2>/dev/null || true && \
    find /app/data/connectors -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
    chown -R soar:soar /app /var/log/soar

ENV PYTHONUNBUFFERED=1
ENV SOAR_CONFIG=/app/config.yaml
ENV SOAR_CONTENT_PYTHON=/app/content-venv/bin/python

EXPOSE 8000
USER soar

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app"]
```

`deploy/stage/Dockerfile.orchestrator` — то же самое плюс существующий
`COPY deploy/stage/config.yaml /app/config.yaml` (не трогается). Прод и
stage расходятся сегодня только этой строкой — двухвенвный блок одинаков в
обоих, копировать без вариаций.

**`SubprocessRunner`** (`orchestrator/core/subprocess_runner.py`) — по
аналогии с уже существующим `_resolve_config_path()` добавляется
`resolve_content_python()` (публичная — переиспользуется `GET /runtime`,
см. [S6]):

```python
def resolve_content_python() -> str:
    """Interpreter for subprocess workflow execution. SOAR_CONTENT_PYTHON is
    set by the Dockerfiles to /app/content-venv/bin/python (two-runtime
    boundary, see docs/concepts/ENTITY-MODEL.md decision 3). Falls back to
    sys.executable when unset — local dev/tests run against a single venv
    without Docker, no second venv to point at."""
    return os.environ.get("SOAR_CONTENT_PYTHON") or sys.executable


_CONTENT_PYTHON = resolve_content_python()
```

`start()` меняет `sys.executable` на `_CONTENT_PYTHON` в
`create_subprocess_exec(...)`. Ничего больше в сигнатуре/env-передаче не
меняется — `safe_env_keys` по-прежнему включает `PYTHONPATH` (на случай, если
контентный venv когда-нибудь понадобится дополнить путём, сегодня не
используется).

`orchestrator/main.py::lifespan` кладёт `app.state.content_python =
resolve_content_python()` — тот же резолвер, не второй источник истины,
используется `GET /runtime`.

**Локальная разработка/тесты не меняются**: без `SOAR_CONTENT_PYTHON` в
env — `sys.executable`, как сегодня, один venv. Дублирование venv локально
не требуется для `pytest`.

## [S4] Контракт зависимостей (решение 1)

`soar/requirements.txt` остаётся файлом, который реально ставится (в
content-venv, см. [S3]) — версии те же, что сегодня, не меняются. Новый
файл `soar/runtime_contract.py` добавляет **метаданные**, которых в
`requirements.txt` нет и быть не должно (не дублировать версии в двух
местах — второй источник истины запрещён и правилами `CLAUDE.md`, и
здравым смыслом): для каждого пакета — по какому имени его импортируют и
относится он к протокольному слою или к вендорскому SDK.

```python
"""SOAR runtime v1 — версионированный контракт содержимого content-venv.

Источник версий пакетов — soar/requirements.txt (единственный, не
дублируется здесь). Этот модуль добавляет то, чего requirements.txt не
несёт: имя для импорта (может не совпадать с именем дистрибутива —
psycopg2-binary → import psycopg2) и границу "протокол или вендор" из
docs/concepts/ENTITY-MODEL.md, решение 1:

- протокольные библиотеки — платформа, конечны, меняются раз в годы;
- вендорские SDK — не платформа, по одному на интеграцию, версионируются
  вместе с чужим API.

Расширение набора — релиз платформы: правка requirements.txt +
CONTRACT здесь, в одном коммите, с тестами (см. [S6] в
docs/compose/specs/2026-07-30-runtime-boundary-design.md).
"""

RUNTIME_VERSION = "1"

CONTRACT: dict[str, dict] = {
    # dist name (как в requirements.txt / importlib.metadata) → метаданные
    "paramiko":         {"import_names": ["paramiko"],   "kind": "protocol"},
    "ldap3":             {"import_names": ["ldap3"],      "kind": "protocol"},
    "smbprotocol":       {"import_names": ["smbclient", "smbprotocol"], "kind": "protocol"},
    "pywinrm":           {"import_names": ["winrm"],      "kind": "protocol"},
    "psycopg2-binary":   {"import_names": ["psycopg2"],   "kind": "protocol"},
    "pymysql":           {"import_names": ["pymysql"],    "kind": "protocol"},
    "pymssql":           {"import_names": ["pymssql"],    "kind": "protocol"},
    "aiosmtplib":        {"import_names": ["aiosmtplib"], "kind": "protocol"},
    "httpx":             {"import_names": ["httpx"],      "kind": "protocol"},
    "requests":          {"import_names": ["requests"],   "kind": "protocol"},
    "pyyaml":            {"import_names": ["yaml"],       "kind": "protocol"},
    "loguru":            {"import_names": ["loguru"],     "kind": "protocol"},
    "elasticsearch":     {"import_names": ["elasticsearch"], "kind": "vendor"},
    "vt-py":             {"import_names": ["vt"],         "kind": "vendor"},
    "aiogram":           {"import_names": ["aiogram"],    "kind": "vendor"},
    "shodan":            {"import_names": ["shodan"],     "kind": "vendor"},
    "pymisp":            {"import_names": ["pymisp"],     "kind": "vendor"},
}
```

Точный список `import_names` для `smbprotocol` проверяется на этапе плана
(пакет публикует несколько top-level модулей — `smbclient` — фасад,
`smbprotocol` — низкий уровень; оба валидны для импорта, отразить оба).

Это закрывает **E2** не правкой Dockerfile "по месту" (ровно так родился
E2), а тем, что `soar/requirements.txt` — уже единственный источник и для
установки ([S3]), и для описания ([S6]).

## [S5] AST-метаданные воркфлоу (закрывает E10.3)

`orchestrator/core/introspect.py` получает `parse_workflow_meta()` — та же
техника, что `parse_classes`/`parse_functions` (никогда не импортирует):

```python
_TYPE_BY_BASE = {
    "ScheduledWorkflow": "scheduled",
    "WebhookWorkflow": "webhook",
    "ManualWorkflow": "manual",
    "BaseWorkflow": "manual",
}
_WORKFLOW_META_FIELDS = ("schedule", "interval", "path", "token")


def _base_name(base: ast.expr) -> str | None:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def parse_workflow_meta(path: Path) -> dict | None:
    """Static AST parse of a workflow module's class-level metadata
    (type/schedule/interval/path/token/docstring) — never imports it.
    Returns None if the module doesn't define a BaseWorkflow subclass."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = {n for b in node.bases if (n := _base_name(b))}
        wf_type = next((_TYPE_BY_BASE[b] for b in base_names if b in _TYPE_BY_BASE), None)
        if wf_type is None:
            continue
        meta = {"type": wf_type, "docstring": ast.get_docstring(node) or ""}
        for item in node.body:
            name = _target_name(item)
            if name in _WORKFLOW_META_FIELDS and isinstance(item.value, ast.Constant):
                meta[name] = item.value.value
        return meta
    return None
```

`orchestrator/main.py::load_workflow_metas` перестаёт импортировать
(`from soar.workflows import workflows as wf_registry; wf_registry.init(...)`)
и вместо этого сканирует те же два каталога, что раньше сканировал
`WorkflowRegistry._discover()`/`_discover_external()` — **тот же порядок
приоритета** (встроенный каталог пакета побеждает при коллизии имени,
сегодня он пуст, но семантику не менять):

```python
def _iter_workflow_files(config) -> Iterator[Path]:
    seen: set[str] = set()
    for base_dir in (str(_SOAR_PKG / "workflows"), config.soar.workflows_dir):
        d = Path(base_dir)
        if not d.exists():
            continue
        for py_file in sorted(d.glob("*.py")):
            if py_file.name.startswith("_") or py_file.name == "base.py":
                continue
            if py_file.stem in seen:
                continue
            seen.add(py_file.stem)
            yield py_file


def load_workflow_metas(config) -> list[WorkflowMeta]:
    state_workflows = load_state(config)
    soar_metas = []
    for py_file in _iter_workflow_files(config):
        try:
            meta = parse_workflow_meta(py_file)
        except SyntaxError as e:
            logger.warning(f"Failed to parse workflow {py_file}: {e}")
            continue
        if meta is None:
            continue
        name = py_file.stem
        saved = state_workflows.get(name)
        enabled = parse_enabled(saved) if saved is not None else True
        token = meta.get("token")
        if meta["type"] == "webhook":
            token = parse_token(saved) or token
        soar_metas.append(WorkflowMeta(
            name=name,
            type=meta["type"],
            enabled=enabled,
            schedule=meta.get("schedule"),
            interval=meta.get("interval"),
            path=meta.get("path"),
            token=token,
            concurrency=ConcurrencyPolicy.ALLOW if meta["type"] == "webhook" else ConcurrencyPolicy.FORBID,
            docstring=meta["docstring"],
        ))

    for name, saved in state_workflows.items():
        if any(m.name == name for m in soar_metas):
            continue
        soar_metas.append(WorkflowMeta(
            name=name, type="scheduled", enabled=parse_enabled(saved),
            concurrency=ConcurrencyPolicy.FORBID,
        ))

    save_state(config, soar_metas)
    return soar_metas
```

Не меняется: сигнатура `load_workflow_metas(config)`, форма
`list[WorkflowMeta]`, все четыре вызывающих места в
`orchestrator/api/workflows.py` (reload после code/history-restore).
**Меняется:** оркестратор больше никогда не импортирует пользовательский
код воркфлоу — только `soar/runner.py` в отдельном процессе на контентном
интерпретаторе делает это ([S3]). Фактическое исполнение (`workflows.init()`
+ `workflows.execute()` в `soar/runner.py`) не трогается — оно и так уже
происходит только в subprocess, а не в оркестраторе.

## [S6] Аудит-хук (решение 2, слой 2)

Новый модуль `soar/audit_hook.py`, устанавливается в `soar/runner.py`
**раньше** `workflows.init()`/`connectors.init()`/`actions.init()` и раньше
сборки `http_client`/`http_client_sync` — то есть первой строкой после
`setup_logging()`.

```python
"""Platform-level наблюдаемость egress/файлов/подпроцессов + deny-policy на
приватные адреса — sys.addaudithook (PEP 578), устанавливается до загрузки
любого контента. Видит любую библиотеку, которой контент это сделал —
httpx, requests, paramiko, ldap3, raw socket — независимо от того, звал ли
код http_client. Хук нельзя снять (sys.removeaudithook не существует) — это
и есть разница со сегодняшним SSRF-guard внутри soar/tools/http_client.py,
который наблюдает только то, что прошло через HttpClient/SyncHttpClient.
_validate_external_url там остаётся как pre-flight (быстрый отказ до
открытия сокета, с понятным ValueError) — хук не заменяет его, а
гарантирует то же самое там, где pre-flight-проверки нет и быть не может
(paramiko, ldap3, pymssql — не HTTP). См. docs/concepts/ENTITY-MODEL.md,
решение 2."""

import ipaddress
import socket
import sys
from typing import Any

from loguru import logger as _log

_WATCHED = {
    "socket.connect", "socket.getaddrinfo", "open",
    "subprocess.Popen", "exec", "ctypes.dlopen",
}

_events: list[dict[str, Any]] = []


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        return False


def _handle(event: str, args: tuple) -> None:
    if event == "socket.connect":
        sock, address = args[0], args[1]
        family = getattr(sock, "family", None)
        if family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple) and address:
            host = address[0]
            if _is_private_ip(str(host)):
                _events.append({"event": "socket.connect.blocked", "address": str(host)})
                raise PermissionError(f"egress to private address {host} blocked by audit hook")
        _events.append({"event": event, "address": str(address)})
    elif event == "subprocess.Popen":
        _events.append({"event": event, "executable": str(args[0])})
    elif event == "open":
        _events.append({"event": event, "path": str(args[0])})
    elif event in ("exec", "ctypes.dlopen"):
        _events.append({"event": event})
    # socket.getaddrinfo — записывается, не блокируется: блокировка на
    # резолве не закрывает ничего, чего не закрывает блокировка на connect,
    # а резолвится DNS чаще, чем реально коннектится (retries, IPv4+IPv6).


def flush() -> None:
    """Batched write — вызывается из soar/runner.py::main() в finally, не на
    каждое событие (иначе на частый socket.connect дорого, см. ENTITY-MODEL
    решение 2: 'внутри только проверка членства в множестве, ... запись
    батчами')."""
    if not _events:
        return
    for e in _events:
        _log.bind(audit=True).info(f"audit: {e}")
    _events.clear()


def install() -> None:
    def hook(event: str, args: tuple) -> None:
        if event in _WATCHED:
            _handle(event, args)
    sys.addaudithook(hook)
```

`soar/runner.py`:

```python
from soar.audit_hook import install as install_audit_hook, flush as flush_audit_hook

setup_logging(level="INFO")
install_audit_hook()   # до любого init() ниже
...

def main():
    try:
        ...
    finally:
        flush_audit_hook()
```

`main()` уже оборачивает `workflows.execute()` в try/except — `flush_audit_hook()`
идёт в `finally`, чтобы события писались и при падении воркфлоу.

**Не удаляется и не меняется:** `_validate_external_url`/`_is_private_ip` в
`soar/tools/http_client.py` и все их тесты — см. пояснение в докстринге
выше. Дублирование логики приватных диапазонов между `http_client.py` и
`audit_hook.py` — сознательное: `soar/` не имеет общего "security"-модуля,
который могли бы делить оба (создавать его ради 10 строк ipaddress-проверки
— это как раз тот избыточный слой абстракции, который правила проекта
просят не заводить); обе копии короткие, стабильные (не менялись с момента
написания) и покрыты тестами независимо.

## [S7] `GET /runtime` (закрывает E9)

Новый роутер `orchestrator/api/runtime.py`, `GET /runtime` — read-only,
без PUT/DELETE (та же категория, что `/tools`, не редактируемое через API
поведение). Регистрируется в `orchestrator/api/__init__.py` и
`orchestrator/main.py` рядом с `tools_router`.

```python
import importlib.metadata
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from orchestrator.auth.dependencies import require_role
from soar.runtime_contract import CONTRACT, RUNTIME_VERSION

router = APIRouter(prefix="/runtime", tags=["runtime"])
_RO = ("viewer", "analyst", "service", "admin", "agent")


def _content_venv_root(content_python: str) -> Path:
    # .../content-venv/bin/python -> .../content-venv
    return Path(content_python).resolve().parent.parent


def _site_packages(venv_root: Path) -> list[str]:
    lib = venv_root / "lib"
    if not lib.is_dir():
        return []
    return [str(p) for p in lib.glob("python3.*/site-packages") if p.is_dir()]


def _python_version(venv_root: Path) -> str | None:
    cfg = venv_root / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    for line in cfg.read_text().splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip()
    return None


def _top_level_names(dist: importlib.metadata.Distribution) -> list[str]:
    raw = dist.read_text("top_level.txt")
    if raw:
        return [n for n in raw.splitlines() if n]
    return [dist.metadata["Name"].replace("-", "_")]


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def get_runtime(request: Request):
    content_python = request.app.state.content_python
    venv_root = _content_venv_root(content_python)
    paths = _site_packages(venv_root)
    dists = list(importlib.metadata.distributions(path=paths)) if paths else []
    by_name = {d.metadata["Name"].lower(): d for d in dists}

    guaranteed = []
    for dist_key, entry in CONTRACT.items():
        d = by_name.get(dist_key.lower())
        if d is None:
            continue  # объявлено контрактом, но не установлено — расхождение сборки, не 500
        guaranteed.append({
            "distribution": d.metadata["Name"],
            "version": d.version,
            "import_names": entry["import_names"],
            "kind": entry["kind"],
        })

    declared = {k.lower() for k in CONTRACT}
    present_not_guaranteed = [
        {"distribution": d.metadata["Name"], "version": d.version, "import_names": _top_level_names(d)}
        for d in dists if d.metadata["Name"].lower() not in declared
    ]

    return {
        "runtime_version": RUNTIME_VERSION,
        "python_version": _python_version(venv_root),
        "guaranteed": sorted(guaranteed, key=lambda x: x["distribution"]),
        "present_not_guaranteed": sorted(present_not_guaranteed, key=lambda x: x["distribution"]),
    }
```

`orchestrator/main.py::lifespan` — `app.state.content_python =
resolve_content_python()` (см. [S3], та же функция, что использует
`SubprocessRunner` — единый источник, не второй расчёт).

**Локально/в тестах** (без Docker, без второго venv) `content_python ==
sys.executable`, `_site_packages` резолвит `sys.prefix`-подобный путь,
который у обычного venv тоже устроен как `<venv>/lib/python3.x/site-packages`
— эндпоинт работает и в этом случае, просто "guaranteed" список будет
таким, что реально стоит в dev-окружении (или пустым, если контракт не
доустановлен локально — не ошибка, а точный ответ на вопрос "что доступно
здесь").

## [S8] Testing Strategy

- `tests/orchestrator/test_subprocess_runner_env.py` /
  `test_subprocess_env.py` — новый тест на `resolve_content_python()`:
  берёт `SOAR_CONTENT_PYTHON` из env, иначе `sys.executable`; тест на
  реальный `create_subprocess_exec` вызов (мокнутый) — использован путь из
  `resolve_content_python()`, не голый `sys.executable`.
- `tests/orchestrator/test_main.py` (или добавить в существующий файл про
  `load_workflow_metas`, если такой уже есть — проверить на этапе плана) —
  тест, что `load_workflow_metas` не импортирует модуль воркфлоу
  (например: временный файл воркфлоу с side-effect на top-level — типа
  `open("/tmp/marker", "w")` — и assert, что маркер не создан после
  `load_workflow_metas`, но метаданные всё равно корректные).
  Regression-тест на существующее поведение: schedule/interval/path/token/
  docstring/type извлекаются идентично прежнему impor-based пути для всех
  реальных сценариев (`ScheduledWorkflow` с `schedule`/`interval`,
  `WebhookWorkflow` с `path`/`token`, `ManualWorkflow` без доп. полей).
- `tests/orchestrator/core/test_introspect.py` — юнит-тесты
  `parse_workflow_meta()` на synthetic файлах (по одному на каждый базовый
  класс + edge cases: нет BaseWorkflow-подкласса → `None`, синтаксическая
  ошибка → `SyntaxError` наружу, докстринг отсутствует → `""`).
- `tests/soar/test_audit_hook.py` — новый файл:
  - `install()` — хук зарегистрирован (`sys.audit(...)` триггерит без
    исключения на разрешённый адрес);
  - `socket.connect` на приватный адрес — `PermissionError`
    (`sys.audit("socket.connect", fake_sock, ("10.0.0.1", 80))` внутри
    `pytest.raises`);
  - `socket.connect` на публичный адрес — событие в `_events`, не
    поднимает;
  - `flush()` — пишет и чистит `_events`; `flush()` на пустом списке — no-op
    (не дергает logger).
  - Важно: `sys.addaudithook` необратим в рамках процесса — тесты не
    вызывают `install()` глобально для всего test-run'а, а тестируют
    `_handle()`/`flush()` напрямую (внутренние функции), плюс один
    dedicated тест на `install()` в отдельном subprocess
    (`subprocess.run([sys.executable, "-c", "..."])`), чтобы не отравить
    хуком остальной pytest-процесс.
- `tests/orchestrator/api/test_runtime.py` — новый файл: `GET /runtime`
  возвращает 200, форму `{runtime_version, python_version, guaranteed,
  present_not_guaranteed}`, `guaranteed` содержит записи только из
  `CONTRACT` и только реально установленные (мокнуть
  `importlib.metadata.distributions` и `app.state.content_python` на
  `sys.executable` в тестовом окружении).
- `tests/soar/test_runtime_contract.py` — `CONTRACT` ключи ⊆ строки в
  `soar/requirements.txt` (защита от расхождения контракта и фактического
  requirements-файла).
- Существующие 24 файла `tests/soar/test_*_connector.py` и
  `tests/soar/tools/test_http_client.py` — не меняются (SSRF-guard внутри
  `http_client.py` не тронут, см. [S6]).
- Docker-специфичная часть ([S3]: двухвенвная сборка, `PATH`,
  `/app/content-venv` не на PATH) не покрывается unit-тестами — верифицируется
  вручную `docker compose build` на `deploy/stage` в рамках приёмки плана
  (см. `docs/compose/plans/2026-07-30-runtime-boundary.md`), не в CI/pytest.

## [S9] Success Criteria

- [ ] `deploy/{prod,stage}/Dockerfile.orchestrator` собирают два venv;
      `soar/requirements.txt` реально устанавливается (закрывает **E2**) —
      проверено `docker compose -f deploy/stage build` без ошибок и ручным
      `docker compose run orchestrator /app/content-venv/bin/python -c
      "import paramiko, ldap3, psycopg2, pymysql, pymssql, aiogram, shodan,
      pymisp, elasticsearch, vt, winrm, smbprotocol"` без ImportError
- [ ] `SubprocessRunner` запускает воркфлоу через `SOAR_CONTENT_PYTHON`
      (в Docker — `/app/content-venv/bin/python`), fallback на
      `sys.executable` вне Docker/тестов
- [ ] `soar/runtime_contract.py` — единственное место, где объявлены
      `import_names`/`kind`; версии не дублируются (источник — по-прежнему
      `soar/requirements.txt`)
- [ ] `load_workflow_metas` не импортирует пользовательский код воркфлоу
      (regression-тест с side-effect-маркером зелёный); формат
      `WorkflowMeta`/поведение `job_manager.set_metas`/`scheduler.reload`
      не меняются для существующих сценариев
- [ ] Аудит-хук установлен в `soar/runner.py` до любого `init()`; блокирует
      `socket.connect` на приватный адрес независимо от библиотеки
      (`PermissionError`, не проходит дальше в вызывающий код);
      пишет батчем в лог джобы через `flush()` в `finally`
- [ ] `GET /runtime` отдаёт контентный venv (не платформенный), пакеты по
      имени импорта, разделение guaranteed/present_not_guaranteed; работает
      и без Docker (fallback на `sys.executable`-venv)
- [ ] Полный прогон `pytest tests/` зелёный, `ruff check .` без находок
- [ ] `docs/agents/known-limitations.md` пункт 10 (E2) снят или
      переформулирован под новое состояние
