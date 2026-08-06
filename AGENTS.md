# AGENTS.md — SOAR Project v0.17

> Это индекс. Детали вынесены в сателлитные файлы под `docs/agents/` и в `CHANGELOG.md` —
> открывай их только когда задача реально их касается (см. Token optimization внизу).

## What is this

SOAR (Security Orchestration, Automation and Response) — система автоматизации инцидентов. Три компонента:

1. **`soar/`** — Python-пакет: контракт и реестры для коннекторов/экшенов/воркфлоу
   (`soar/connectors/base.py`+`_proxy.py`, `soar/actions/`, `soar/workflows/`),
   зависимостный контракт content-venv (`soar/runtime_contract.py`). Сами 24
   встроенных коннектора (SSH, AD, FreeIPA, Elastic, SecurityOnion, Wazuh,
   PostgreSQL/MySQL/MSSQL, Telegram, SMTP, VirusTotal, Abuse.ch, File, WinRM,
   SMB, Shodan, Fofa, Censys, MISP, RstCloud, Kaspersky OpenTip, URLhaus,
   crt.sh) — не в этом репозитории: отдельный контентпак
   (`soar-content-pack`, локальный git-репозиторий, сиблинг этого чекаута),
   ставится через `soarctl content install`/`POST /connectors/pack/install`,
   см. `docs/compose/reports/content-as-contentpack.md`
2. **`orchestrator/`** — FastAPI сервис: очередь задач, воркеры, планировщик, git-версионирование
3. **`ui/`** — Vue.js SPA: стенд для ручного тестирования, дорабатывается до
   продакшен-юзабельности (точки контроля, видимость логов и аудита — см.
   `docs/compose/specs/2026-07-29-ui-control-visibility-design.md`), но
   остаётся вне основного продукта. Основной API-доступ — напрямую на порту
   8000 (orchestrator). Тесты — vitest, `cd ui && npm test`

## Модель сущностей — суть проекта

> Нормативный раздел. Объяснение, карта текущего дрейфа и план возврата —
> [`docs/concepts/ENTITY-MODEL.md`](docs/concepts/ENTITY-MODEL.md).
> Эти правила старше любой задачи: задача, которая их нарушает, решается
> неправильно, даже если тесты зелёные.

Смысл схемы — разгрузить рабочий поток от рутины и **прозрачно** добавить
логирование и аудит, оставив в потоке только логику SOAR-автоматизации.
Низкий код (как Shuffle/n8n) в виде Python, а не в виде мышки.

| Сущность | Что это | Кто пишет | Где живёт |
|---|---|---|---|
| **Коннектор** | интеграция с внешним сервисом/API; конфиг задаёт несколько именованных инстансов под разные креды | пользователь / контентпак | `connectors_dir` |
| **Экшен** | сниппет прикладной логики (функция, класс); внутрянки проекта не касается | пользователь | `actions_dir` |
| **Инструмент (tool)** | обвязка платформы с доступом во внутрянку (Redis, БД, кэш); **нередактируем** | проект | `soar/tools/` |
| **Рабочий поток** | сценарий автоматизации; наследует базовый класс, фиксированная сигнатура | пользователь | `workflows_dir` |

**Принцип 1. Проект даёт гарантии, контент их получает.** Критерий:
если сущность удалить, останется ли продукт продуктом? Убрать все
коннекторы — очередь, воркеры, изоляция, git, RBAC, аудит остаются.
Убрать `BaseConnector`/реестр/схему конфига — не остаётся ничего.
Значит тела коннекторов — контент, а контракт и реестры — проект.
Контент версионируется отдельно, ставится без пересборки образа, несёт
свои зависимости и **может быть чужим**. Контракт всегда остаётся в
проекте: уедет контракт в контент — контент начнёт менять правила.

**Принцип 2. Прозрачность обеспечивает платформа, а не дисциплина автора.**
Логирование, аудит, dry-run и редакция секретов реализуются **на границе**,
где платформа отдаёт сущность рабочему потоку, — не внутри кода сущности.
Наследование от `BaseConnector` — маркер типа для discovery, а не механизм
логирования: контент волен не звать `_ensure_connected` и определять методы
как угодно.

**Принцип 3. Одна сущность — одно место жительства.** У сущности ровно один
источник исполнения. Пакет `soar/` содержит контракт и реестр; контент живёт
в настраиваемых каталогах. Никаких «копия в пакете и копия в данных».

**Принцип 4. Проект объясняет себя через API.** Тот, кто пишет коннектор,
экшен или поток — человек или LLM-агент — узнаёт всё необходимое из API, не
читая исходники и не имея доступа к хосту. Уже действует для инструментов
(`GET /tools`), сигнатур (`/describe`) и полей конфига (`/schema`); правило
общее. Сюда же входит **окружение исполнения**: что доступно для импорта и
что из этого гарантировано платформой — `GET /runtime` отдаёт
`soar/runtime_contract.py` + фактически установленные пакеты content-venv
(закрыто в Runtime Boundary Phase 1, E9). Проверка на нарушение: если ответ
на вопрос «что мне доступно?» требует `docker exec`, чтения
`requirements.txt` или похода к админу — принцип нарушен.

**Принцип 5. Рантайм контента отделён от рантайма платформы.** У контента
свой интерпретатор со своим набором пакетов; внутренности платформы
(драйверы БД, JWT, миграции, ORM) недоступны ему физически, а не по
договорённости. Это граница зависимостей, не песочница: защищаемся от
неаккуратного и умеренно враждебного контента, не от целенаправленного
атакующего. `SubprocessRunner` запускает `soar.runner` на отдельном
`content-venv` (`SOAR_CONTENT_PYTHON`, закрыто в Runtime Boundary Phase 1,
E10) — платформенные пакеты (FastAPI, SQLAlchemy, JWT) физически не
установлены туда. Слой изоляции 3 (Фаза 4, privilege narrowing) сужает
дальше: субпроцесс получает конфиг-срез только с используемыми
connector-инстансами (статический AST-вывод из `from soar.connectors.
<type> import <instance>`, не полный `config.yaml` — JWT-секрет и
`database.url` физически не передаются), а на POSIX/Docker опционально
(`jobs.runner_uid`) — отдельный UID/GID + `RLIMIT_AS`/`RLIMIT_CPU`/
`RLIMIT_NPROC`, см. `docs/agents/security-patterns.md`.

**Зависимости — контракт, а не список удобства.** Установки пакетов в
рантайме нет и не будет: air-gap (нет индекса) и эфемерность контейнера.
Набор запекается в образ, объявляется явно и версионируется; граница
набора — «протокол или вендор»: протокольные библиотеки (`paramiko`,
`ldap3`, `smbprotocol`, `pywinrm`, драйверы БД, `httpx`/`requests`) —
платформа, вендорские SDK (`vt-py`, `shodan`, `pymisp`) — нет. Вендорский
SDK вдобавок обходит `http_client`, то есть ломает принцип 2 —
HTTP-интеграцию писать на `http_client`. Детали и обоснование —
`ENTITY-MODEL.md`, решения 1–4.

**Наблюдаемость — два уровня, не один.** Прокси на границе реестра говорит
намерение (какой инстанс, какой метод, какие аргументы); аудит-хук
`sys.addaudithook` в `soar/runner.py` говорит факт (куда реально ушло
соединение, что открыто, что запущено) — независимо от библиотеки и без
возможности снять хук. Прокси **не** граница безопасности: он в одном
процессе с контентом.

Правило действует во всех четырёх слоях: `soar/workflows/` содержит только
`__init__.py`+`base.py`, `soar/actions/` — только `__init__.py`,
`soar/connectors/` — только `__init__.py`/`base.py`/`_proxy.py`. Все 24
встроенных коннектора — контент, живут в отдельном репозитории пака
(`soar-content-pack`, закрыто в Content-as-Contentpack Phase 3, E1/E4).

## Stack

- Python 3.11+
- FastAPI + uvicorn (orchestrator)
- APScheduler (cron workflows)
- loguru (логирование)
- pytest + pytest-asyncio (тесты)
- Redis (опциональный бэкенд очереди)
- python-jose (JWT HS256)
- bcrypt (password hashing, direct — не через passlib)
- SQLAlchemy 2.0 async + asyncpg (auth + опционально job-история, `database:` конфиг)
- Alembic (продакшн миграции, `alembic/`)
- aiosqlite (dev/test SQLite, дефолт `database.url`)
- Vue 3 + Vite (UI)
- Docker Compose (deploy)

## Commands

```bash
# Тесты
python -m pytest tests/ -v

# Конкретный тест
python -m pytest tests/orchestrator/test_job_manager.py -v

# Только orchestrator
python -m pytest tests/orchestrator/ -v

# Только SOAR модуль
python -m pytest tests/soar/ -v

# Coverage
python -m pytest tests/ --cov=soar --cov=orchestrator

# Lint (ruff)
ruff check .

# Lint auto-fix
ruff check --fix .

# Type check (mypy)
mypy orchestrator/ soar/ --ignore-missing-imports

# UI dev server (port 3000, proxies to orchestrator:8000)
cd ui && npm install && npm run dev

# UI build
cd ui && npm run build

# Stage deploy (Docker) — internal QA, build: from source
cd deploy/stage && docker compose up --build

# Prod deploy (Docker, distributable) — build machine, then transfer bundle (air-gap)
python deploy/soarctl package --version X.Y.Z --output soar-bundle-X.Y.Z.tar.gz
# target machine (offline from here on)
python soarctl install soar-bundle-X.Y.Z.tar.gz --dir soar-prod && cd soar-prod
python soarctl init && python soarctl up && python soarctl migrate --fresh

# Prod deploy, on-site (target machine has internet) — checkout is the instance
git clone <url> soar && cd soar
./soarctl install && ./soarctl init && ./soarctl up && ./soarctl migrate --fresh
```

## Architecture

```
orchestrator/
├── main.py                    # FastAPI app + lifespan, все зависимости в app.state
├── config.py                  # OrchestratorConfig (Pydantic), читает config.yaml
├── models/
│   ├── __init__.py            # JobStatus, ConcurrencyPolicy (enum)
│   ├── job.py                 # WorkflowJob (dataclass)
│   └── workflow_meta.py       # WorkflowMeta (dataclass)
├── core/
│   ├── queue/                 # AbstractJobQueue → InMemoryQueue | RedisQueue | SQLQueue
│   │   └── sql_queue.py        # SQLQueue — poll-claim поверх workflow_jobs (FOR UPDATE SKIP LOCKED / SQLite serialization), см. Queue backend
│   ├── worker.py              # Worker — один воркер, цикл pop → execute; после запуска парсит SOAR_AUDIT_EVENT из job.log (audit_parse.py) → AuditLog, если сконструирован с db_session_factory (не проваливает джобу при сбое парсинга/записи)
│   ├── worker_pool.py         # WorkerPool — N воркеров как asyncio tasks
│   ├── scheduler.py           # OrchestratorScheduler (APScheduler) — + периодическая retention_cleanup job (jobs.retention_days > 0)
│   ├── job_manager.py         # JobManager — координатор, enqueue/cancel
│   ├── subprocess_runner.py   # Запуск workflows как subprocess
│   ├── git_manager.py         # Git операции через subprocess (commit принимает author_name/author_email override; nothing-to-commit определяется через `git diff --cached --quiet`, не string-match stderr)
│   ├── history.py             # Тонкие обёртки над GitManager для history/diff/restore (общие для workflows/actions/connectors)
│   ├── workflow_state.py      # Единственный читатель/писатель orchestrator_state.yaml (enable/disable + webhook token)
│   ├── introspect.py          # parse_classes/parse_functions/parse_workflow_meta/parse_tool_registry — AST-интроспекция без импорта, общая для tools.py/actions.py/connectors.py/workflows.py; parse_classes также извлекает fields (тип+дефолт) и hidden_fields (HIDDEN_FIELDS) для connector schema; parse_tool_registry читает TOOL_REGISTRY (GET /tools, tools-redesign)
│   ├── audit_parse.py          # parse_audit_events() — парсит SOAR_AUDIT_EVENT-строки из лога джобы (пишет soar/connectors/_proxy.py), Worker._execute передаёт результат в audit.service.record_job_event
│   ├── openapi_generator.py    # OpenAPIGenerator — перенесён из soar/tools/openapi.py (Фаза 2, E5): механизм оркестратора (генерация коннектора из спеки), не runtime-инструмент воркфлоу, единственный потребитель — api/connectors.py
│   ├── pack_install.py          # read_manifest/check_runtime_compat/check_dependencies/plan_install/apply_install/apply_install_dir — чистая install-логика контентпака (Фаза 3), общая для api/packs.py (zip-загрузка) и main.py::seed_connector_pack (base pack, директория, каждый старт)
│   └── net.py                 # resolve_client_ip() — trusted-proxy-aware IP, общий для rate limiter/access log/audit
├── store/
│   ├── base.py                 # AbstractJobStore — интерфейс (save/get/list/count_by_status/stats/recover_on_startup/purge_old)
│   ├── job_store.py            # InMemoryJobStore (JobStore — алиас для обратной совместимости); purge_old() — no-op
│   ├── models.py                # SQLAlchemy ORM: JobRecord (workflow_jobs)
│   ├── mapping.py               # job_to_record/record_to_job — общие для SQLJobStore и SQLQueue, не дублируются
│   └── sql_job_store.py        # SQLJobStore — персистентный джоб-стор поверх database.url; purge_old() удаляет старые завершённые записи по jobs.retention_days
├── auth/                       # models/schemas/service/dependencies/router/cli — см. File map
├── audit/                      # models (AuditLog) + service (record, git_author) — см. File map
├── db/                         # base (table_prefix), session (init_engine/init_db/get_db) — см. File map
└── api/
    ├── workflows.py            # GET/POST enable/disable, reload + CRUD кода workflow + history/diff/restore
    ├── actions.py               # CRUD actions + templates + history/diff/restore + GET {name}/describe; GET /actions — AST-only (parse_functions), лишний public callable на файл — отдельная запись, не импортирует actions_dir (граница рантайма из Фазы 1 — импорт контента только внутри soar.runner)
    ├── connectors.py            # CRUD connectors + code/config + OpenAPI generate/preview (orchestrator/core/openapi_generator.py) + history/diff/restore + GET {name}/describe
    ├── packs.py                  # POST /connectors/pack/install — установка контентпака (admin-only, conflict-preflight+force, audit); orchestrator/core/pack_install.py — чистая логика (read_manifest/plan_install/apply_install)
    ├── jobs.py                  # POST запуск, GET статус, cancel
    ├── webhooks.py              # POST webhook с токеном
    ├── logs.py                  # GET лог + SSE стрим
    ├── status.py                # GET /status, GET /health
    ├── transfer.py               # POST export/import — импорт/экспорт конфигурации
    ├── tools.py                  # GET /tools — read-only discovery (AST, без импорта) для soar/tools/; TOOL_REGISTRY (kind: class/instance/factory) резолвится через _resolve — нерезолвящееся имя отдаёт {"error": "unresolved"}, не тихую заглушку
    ├── runtime.py                 # GET /runtime — read-only, содержимое content-venv по soar/runtime_contract.py (guaranteed/present_not_guaranteed)
    ├── prompts.py                 # GET /prompts/system (read-only, versioned с кодом) + GET/PUT /prompts/user (admin, git-CRUD)
    ├── audit.py                  # GET /audit-log — admin-only, paginated, фильтры
    └── validation.py              # validate_name, validate_path_within, SSRF validation

soar/
├── connectors/                 # Только контракт+реестр — __init__.py (ConnectorRegistry — dict[type][instance], namespace по типу), base.py (BaseConnector, HIDDEN_FIELDS/MUTATING_METHODS), _proxy.py. Сами 24 встроенных коннектора — НЕ здесь с Phase 3 (content-as-contentpack): отдельный репозиторий `soar-content-pack` (сиблинг этого чекаута, локальный, без remote), ставится в connectors_dir через soarctl content install/POST /connectors/pack/install/сидинг на старте — см. File map и docs/compose/reports/content-as-contentpack.md
│   └── _proxy.py                # ConnectorProxy — единственный способ получить коннектор (оба фасада: `from soar.connectors.<type> import <instance>` и `connectors.<instance>`); логирует SOAR_AUDIT_EVENT, редактирует HIDDEN_FIELDS, блокирует MUTATING_METHODS под dry_run
├── runtime_state.py             # process-wide dry_run flag (один subprocess = одна джоба) — set_dry_run/is_dry_run, читает ConnectorProxy
├── actions/__init__.py         # ActionsRegistry — автообнаружение actions, регистрирует все public top-level callables модуля (не только одноимённый файлу)
├── workflows/                  # __init__.py (WorkflowRegistry), base.py (BaseWorkflow/ScheduledWorkflow/WebhookWorkflow/ManualWorkflow)
├── tools/                      # __init__.py::TOOL_REGISTRY — единственный источник того, что видно GET /tools (class/instance/factory); watermark.py (WatermarkStore/SeenStore + watermark_store()/seen_store() фабрики, путь из soar.state_dir), http_client.py (LoggingHttpClient/CachingHttpClient — httpx.Client-подклассы, единый send() покрывает любой HTTP-метод и .json()/.content; new_client(verify=...) — для connect_impl с нестандартным TLS-доверием или persistent-состоянием); _cache.py/_net.py — внутренняя механика (CacheBackend/InMemoryCache/RedisCache, SSRF-guard), не в TOOL_REGISTRY. См. File map. OpenAPIGenerator — не здесь, см. orchestrator/core/openapi_generator.py
├── runtime_contract.py         # CONTRACT (dist name → import_names/kind) + RUNTIME_VERSION — версионированный контракт content-venv, источник для GET /runtime; версии пакетов по-прежнему только в soar/requirements.txt
├── audit_hook.py                # sys.addaudithook — платформенная наблюдаемость egress/файлов/подпроцессов + deny-policy на приватные адреса, ставится в runner.py до любого init()
├── runner.py                   # Точка входа для subprocess workflows — см. Runner contract; ставит audit-хук, собирает единственный tools.http_client из SOAR_CONFIG (заполняет http_client.py::_shared_cache/_shared_default_ttl/_shared_domain_ttl для new_client()), выставляет runtime_state.set_dry_run(context["dry_run"]) до workflows.execute() — до workflows.init()/connectors.init()/actions.init() — верхнеуровневый `from soar.tools import http_client` в пользовательском коде видит сконфигурированный инстанс
└── examples/nadproject_integration.py

ui/src/                         # Vue 3 SPA, полный список views — см. File map
alembic/                        # Alembic-миграции (auth + workflow_jobs + audit_log таблицы), см. docs/agents/config-reference.md
deploy/stage/                   # QA docker-compose (build: from source) + Makefile
deploy/prod/                    # Distributable profile — image: не build:, config.yaml не в git, см. README.md ("Деплой")
soarctl                         # Root-level bash wrapper (`./soarctl ...`) — see deploy/soarctl below
deploy/soarctl, soarctl_lib/    # Host-layer CLI: package/install/init/up/update/migrate/users/backup/doctor/content
                                 # git_source.py — on-site install, in-place in <checkout>/deploy/prod (no bundle/air-gap);
                                 # paths.instance_dir() auto-discovers cwd/checkout the way `git` finds its repo root

tests/
├── soar/                       # flat files: test_<connector>_connector.py (mocked), test_workflows.py, tools/
├── orchestrator/               # api/, store/, test_job_manager.py, test_worker.py, test_scheduler.py, ...
└── deploy/                     # test_soarctl_*.py — все на моках subprocess
```

## API Endpoints

Полные таблицы (workflows/actions/connectors/tools/transfer/jobs/webhooks/logs/status/auth/audit) —
**[docs/agents/api-reference.md](docs/agents/api-reference.md)**.

Быстрый ориентир по префиксам: `/workflows`, `/actions`, `/connectors` (CRUD кода/конфига,
history/diff/restore, `/describe` — сигнатуры/докстринг без импорта, тот же AST-паттерн, что `/tools`;
`/schema` — типизированные поля + `hidden: bool`; конфиг/история/diff редактируют значения hidden-полей
для всех ролей включая admin, см. Security patterns),
`/jobs`, `/webhooks/{name}`, `/logs/{id}`, `/status`, `/health` (без auth), `/tools` (read-only),
`/runtime` (read-only, содержимое content-venv по контракту, см. E9/`ENTITY-MODEL.md`),
`/prompts/system` (read-only, встроенный), `/prompts/user` (admin, git-CRUD), `/transfer/{export,import}`,
`/auth/*`, `/audit-log` (admin).

## Key patterns

### App state (orchestrator)
Все зависимости живут в `app.state` и достаются через `request.app.state`:
```python
job_manager = request.app.state.job_manager
pool = request.app.state.pool
```

### Workflow lifecycle
1. `JobManager.enqueue()` → проверка enabled/concurrency → создание WorkflowJob → push в очередь
2. `Worker.run()` → pop из очереди → `SubprocessRunner.start()` → ожидание с таймаутом
3. Статусы: PENDING → RUNNING → COMPLETED | FAILED | TIMEOUT | CANCELLED

### Connector lazy init
Коннекторы подключаются при первом вызове метода через `_ensure_connected()`.

### Доступ к коннекторам — только через `ConnectorProxy` (Фаза 2)
Два фасада, один механизм: `from soar.connectors.<type> import <instance>`
(концептная форма — модульный `__getattr__`-шим,
`soar/connectors/__init__.py::_install_shims`) и `from soar.connectors import
connectors` + `connectors.<instance>` (плоский путь,
`ConnectorRegistry.__getattr__`) — оба **всегда** возвращают
`ConnectorProxy` (`soar/connectors/_proxy.py`), никогда сырой
`BaseConnector`-инстанс. Опечатка в имени инстанса при концептной форме —
`AttributeError` на импорте, а не в рантайме джобы. Прокси оборачивает
каждый публичный вызов метода:
- пишет `SOAR_AUDIT_EVENT connector.call target=<type>.<instance>.<method>
  args=... kwargs=... duration_ms=... outcome=...` в лог джобы; ключи
  `kwargs`, объявленные в class-level `HIDDEN_FIELDS` коннектора,
  редактируются в логе (не в реальном вызове);
- блокирует вызов, если метод объявлен в class-level `MUTATING_METHODS`
  коннектора и `context["dry_run"]` истинен (`soar/runtime_state.py`,
  выставляется в `soar/runner.py::main()` из `context` до
  `workflows.execute()`) — централизованно, не по добровольному соглашению
  воркфлоу.

`Worker._execute` (`orchestrator/core/worker.py`) парсит `SOAR_AUDIT_EVENT`
из лога завершённой джобы (`orchestrator/core/audit_parse.py`) и пишет
`AuditLog`-записи через `audit.service.record_job_event()` — синтетический
actor `job:<workflow_name>`, тот же паттерн, что у webhook-триггернутых
job.create. Ошибка парсинга/записи аудита не проваливает джобу
(observability, не exec path).

`BaseConnector.MUTATING_METHODS: ClassVar[set[str]] = set()` — та же
конвенция, что `HIDDEN_FIELDS`: каждый коннектор объявляет свой набор
мутирующих методов (`send_*`, `create_*`, `delete_*`, `exec_*`, `put_*`,
`index`, ...); read-only (`get_*`/`search`/`list_*`/`query` без побочных
эффектов) не входят.

### Git auto-commit
Любое изменение файла через API автоматически коммитится в git. `GitManager.commit()`
принимает опциональные `author_name`/`author_email` — мутирующие роуты передают
реального пользователя (`audit.service.git_author(user)`), иначе используется
дефолт из `config.git.author_name/author_email`. `GitManager.restore()` принимает
те же kwargs (используется history/restore ручками, см. API reference) —
откат тоже коммитится от актора, не от дефолта.

### История/diff/restore (orchestrator/core/history.py)
Тонкие обёртки (`list_history`/`get_version`/`diff_versions`/`restore_version`)
над уже существующими методами `GitManager` — общий модуль, чтобы не дублировать
одну и ту же обвязку в трёх роутерах (workflows/actions/connectors). Read-ручки
на существующих `_RO`-ролях, restore — на `_ADMIN`, каждый restore пишет
`AuditLog`-запись через `audit.service.record()`. Restore workflow-кода
дополнительно триггерит тот же reload, что `PUT .../code`
(`load_workflow_metas` + `job_manager.set_metas` + `scheduler.reload`); restore
action/connector — без reload, как и текущие `PUT`.

### Request logging / correlation id (orchestrator/main.py)
`access_log_middleware` — последний зарегистрированный `@app.middleware("http")`
(это делает его самым внешним слоем, оборачивающим CORS/body-limit/rate-limit —
важно для того, чтобы он логировал и тэгал их 413/429 ответы тоже). Генерирует
`request_id`, кладёт в `request.state.request_id` и заголовок ответа
`X-Request-ID`, оборачивает обработку в `logger.contextualize(request_id=...)`.
Одна строка лога на запрос: method/path/status/duration_ms/client_ip/user_id.
`request.state.user_id`/`user_role` выставляет `get_current_user`
(`orchestrator/auth/dependencies.py`) на всех return-путях — это единственный
способ добраться до identity из middleware, не дублируя JWT/API-key логику.

### Security-event logging
Точки отказа, которые раньше падали молча, теперь пишут `logger.warning(...)`:
401/403 в `auth/dependencies.py`, 429 в `main.py::rate_limit_middleware`,
невалидный `X-Webhook-Token` в `api/webhooks.py`. Без логирования тела/токена —
только факт отказа + IP/path.

### Audit trail (orchestrator/audit/)
Отдельно от access-лога — таблица `audit_log` (та же БД, что job-история и auth),
пишется явным вызовом `audit.service.record(db, user=..., action=..., resource_type=...,
resource_id=..., request=..., detail=...)` из мутирующего роута (после успешной
мутации, тем же паттерном, что и существующий `git.commit(...)`), не
generic-перехватчиком — только сам роут знает семантику ресурса и что не стоит
логировать (секреты в теле). Читается через `GET /audit-log` (admin-only).
`POST /transfer/export` и `POST /transfer/import` (S3) теперь тоже пишут
(`transfer.export`/`transfer.import`, только имена сущностей в `detail`, не
содержимое файлов; conflict-preflight `/import` без `force` — read-only,
audit не пишет). `POST /jobs` и `POST /webhooks/{name}` (S4) пишут
`job.create` — у вебхука нет `CurrentUser` (нет JWT/RBAC на этом роуте),
поэтому актор синтетический: `CurrentUser(id=0, role="service", type="webhook",
username=f"webhook:{workflow_name}")`, третье значение `actor_type` (кроме
`"user"`/`"service"`).

### Subprocess execution
Workflows запускаются как отдельные процессы через `soar.runner`:
- stdout перенаправляется в файл лога
- Контекст передаётся через env vars (SOAR_CONTEXT)
- Actions и connectors инициализируются в subprocess
- `SOAR_CONFIG` субпроцесса — не `orchestrator/config.yaml`, а временный
  конфиг-срез (`SubprocessRunner.build_scoped_config`, Фаза 4): только
  connector-инстансы, статически найденные в импортах воркфлоу, каталог
  удаляется в `Worker._execute`'s `finally` — см. Security patterns ниже

## Runner contract (soar/runner.py)

Entry point for subprocess workflow execution. Called by `SubprocessRunner`.

**Reads from environment:**
- `SOAR_CONFIG` — path to config.yaml
- `SOAR_WORKFLOW_NAME` — workflow registry key (**имя файла без .py**, не имя класса)
- `SOAR_CONTEXT` — JSON-encoded context dict
- `SOAR_JOB_ID`, `SOAR_LOG_PATH` — тоже передаются (информационно)

**Writes to stdout:** last line must be JSON-encoded `WorkflowResult`:
```json
{"success": true, "data": {...}, "error": null}
```

На неудаче `"error"` — полный traceback (`WorkflowResult.traceback`), не
`str(exception)`. `main()` оборачивает весь вызов `workflows.execute()` в
try/except — ошибка **до** входа в `run()` (workflow не найден, упал
конструктор) тоже даёт эту же структурированную JSON-строку, а не
неперехваченное исключение без финальной строки в логе.

**Exit codes:** `0` = success, `1` = failure (stdout JSON still required)

**Do not change this contract** without updating `SubprocessRunner` and tests simultaneously.

### Queue backend и Database backend

Полное описание конфигурации (Redis/memory очередь, `database.url`, `table_prefix`,
`jobs.persistence`) — **[docs/agents/config-reference.md](docs/agents/config-reference.md)**.

**Landmine, если трогаешь Alembic-миграции:** `create_all()` выполняется на каждом
старте контейнера и создаёт отсутствующие таблицы раньше, чем оператор успевает
вызвать Alembic. Для миграции, которая **только добавляет новую таблицу**, правильная
последовательность — `docker compose up --build -d` → `alembic stamp head` (не
`upgrade head`, иначе `DuplicateTableError`). `upgrade head` нужен только когда
миграция меняет существующую таблицу. Полное объяснение — в config-reference.md.

## Security patterns

Полное описание (input validation, connector security, authentication/JWT/RBAC,
rate limiting, subprocess isolation, API hardening) —
**[docs/agents/security-patterns.md](docs/agents/security-patterns.md)**.

Коротко: `orchestrator/api/validation.py` валидирует имена/пути/commit-хэши и код
(`ast.parse`, без импорта) перед записью; auth — JWT + refresh + API keys + RBAC
(`admin`/`analyst`/`viewer`/`service`/`agent` — `agent`: код+jobs, не
user-management/API-keys/audit-log/transfer, см. security-patterns.md),
`auth.secret_key = ""` → анонимный admin; rate limit 120/60s (5/60s на login);
все HTTP-коннекторы — `timeout=30`; job-субпроцесс получает конфиг-срез, не
полный `config.yaml` (credential scoping), и опционально (POSIX/Docker,
`jobs.runner_uid`) отдельный UID + `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_NPROC`
(privilege narrowing, Фаза 4) — см. security-patterns.md.

## Known limitations

Полные описания + workaround — **[docs/agents/known-limitations.md](docs/agents/known-limitations.md)**.

1. `ConcurrencyPolicy.QUEUE` — race между двумя QUEUE-jobs (busy-wait в Worker)
2. RedisQueue — at-most-once, может терять сообщения при обрыве соединения (дефолт `deploy/prod`/`deploy/stage` с v0.12 — `queue.backend: sql`, устраняет этот риск для критичных workflows)
3. Crash recovery работает только при `jobs.persistence: sql`
4. JobStore теряет историю при рестарте только на дефолте `persistence: memory`
5. `keep_completed` eviction — FIFO, не LRU
6. `AuditLog.actor_name` для JWT — числовой id, не логин
7. `PATCH /auth/users/{id}` не защищает от деактивации последнего admin'а (принято как остаточный риск — recovery вне API через `orchestrator/auth/cli.py create-user --role admin`)
8. Мультиинстансность вне scope `soarctl` (нет CLI-контекста нескольких инстансов)
9. ~~Правка кода встроенного коннектора через API молча не применяется — исполняется копия из пакета, а не из `connectors_dir`~~ — закрыто в Content-as-Contentpack Phase 3 (E1, E4): 24 встроенных коннектора переехали в отдельный репозиторий пака, `soar/connectors/` больше не содержит копий
10. ~~Зависимости 11 из 24 встроенных коннекторов не установлены в образ~~ — закрыто в Runtime Boundary Phase 1 (E2)
11. ~~Контент исполняется в рантайме платформы — тот же интерпретатор и те же site-packages, что у оркестратора; воркфлоу импортируются в процесс оркестратора при reload~~ — закрыто в Runtime Boundary Phase 1 (E10, включая E10.3): `deploy/{prod,stage}` теперь собирают отдельный `content-venv`, `SubprocessRunner`/`soar/runner.py` запускаются на нём (`SOAR_CONTENT_PYTHON`); `load_workflow_metas` больше не импортирует пользовательский код (AST-парсинг). Окружение исполнения теперь описано по API — `GET /runtime` (E9)

## File map (для быстрого навигации)

| Что нужно | Куда смотреть |
|-----------|---------------|
| Добавить API эндпоинт | `orchestrator/api/*.py` |
| Новый встроенный коннектор (одна из 24 базовых интеграций) | `soar-content-pack` (отдельный репозиторий, сиблинг этого чекаута) — `connectors/`, скопировать `elastic/` как шаблон; `tools/gen_manifest.py` перегенерирует `manifest.yaml` (AST, не импортирует). Этот репозиторий — не часть модели сущностей `soar/`: контракт (`base.py`/`_proxy.py`/`MUTATING_METHODS`) остаётся здесь, тело коннектора — там |
| Коннектор конкретного вендора/протокола (Telegram, SMTP, SSH, AD, FreeIPA, Elastic, SecurityOnion, Wazuh, PostgreSQL/MySQL/MSSQL, VirusTotal, Abuse.ch, File, WinRM, SMB, Shodan, Fofa, Censys, MISP, RstCloud, Kaspersky OpenTip, URLhaus, crt.sh) | `soar-content-pack/connectors/<name>/` — см. `docs/compose/reports/content-as-contentpack.md` для полного списка методов на каждый (перенесено туда без изменения кода) |
| Установка/обновление базового пака коннекторов | `soarctl content install\|list\|remove` (`deploy/soarctl_lib/content.py`), `POST /connectors/pack/install` (`orchestrator/api/packs.py`, admin-only), сидинг на старте — `orchestrator/main.py::seed_connector_pack` (каждый старт, не только на пустом volume — закрывает E4) |
| Install-планирование пака (чистая логика) | `orchestrator/core/pack_install.py` — `read_manifest`/`check_runtime_compat`/`check_dependencies`/`plan_install`/`apply_install`, маркер происхождения `.soar-content.yaml` |
| Watermark / дедуп событий | `soar/tools/watermark.py` — WatermarkStore, SeenStore (durable JSON, generic) + `watermark_store(name)`/`seen_store(name, ttl)` фабрики (путь строится из `soar.state_dir` конфига, синглтон-контракт как у `http_client`) |
| HTTP client (логирование + опциональный кэш) | `soar/tools/http_client.py` — `LoggingHttpClient`/`CachingHttpClient` (httpx.Client-подклассы, единый `send()`, `http_client` синглтон), `new_client(verify=...)` для нестандартного TLS-доверия/persistent-состояния, `http_client:` секция конфига, см. `docs/agents/config-reference.md` |
| Connector config schema / секреты | `orchestrator/core/introspect.py` (`_fields`/`_hidden_fields`), `orchestrator/api/connectors.py` (`GET /schema`, редакция config/history/diff), `HIDDEN_FIELDS` на каждом коннекторе |
| Connector dry-run / audit trail | `soar/connectors/_proxy.py` (`ConnectorProxy`, `MUTATING_METHODS`), `soar/runtime_state.py` (`is_dry_run`), `orchestrator/core/audit_parse.py` + `orchestrator/audit/service.py::record_job_event` (парсинг `SOAR_AUDIT_EVENT` → `AuditLog` в `Worker._execute`) |
| Новый action | `soar/actions/`, один файл может экспортировать несколько public top-level функций — все регистрируются под своим именем (`ActionsRegistry`, E7); `GET /actions` листит их через AST, без импорта |
| Новый workflow | `soar/workflows/`, наследовать от `ScheduledWorkflow`/`WebhookWorkflow`/`ManualWorkflow` |
| Шаблон workflow | `orchestrator/api/workflows.py` — TEMPLATES dict |
| Изменить модель | `orchestrator/models/` |
| Очередь задач | `orchestrator/core/queue/` — memory / redis / sql (`sql_queue.py`, дефолт `deploy/prod`/`deploy/stage`), см. `docs/agents/config-reference.md` |
| Воркеры | `orchestrator/core/worker.py`, `worker_pool.py` |
| Планировщик | `orchestrator/core/scheduler.py` |
| Runner | `soar/runner.py` — точка входа для subprocess |
| История/diff/restore (движок) | `orchestrator/core/history.py` — обёртка над `GitManager` для workflows/actions/connectors |
| Workflow enable/disable state | `orchestrator/core/workflow_state.py` — единственный читатель/писатель `orchestrator_state.yaml` |
| AST-интроспекция (describe) | `orchestrator/core/introspect.py` — `parse_classes`/`parse_functions`, общий для `/tools`, `/actions/{name}/describe`, `/connectors/{name}/describe` |
| Системный/пользовательский промпт агента | `orchestrator/api/prompts.py`, текст — `orchestrator/prompts/system_prompt.md` |
| Auth endpoints | `orchestrator/auth/router.py` — /auth/login, /auth/refresh, /auth/logout, /auth/me, /auth/keys, /auth/users |
| Auth dependencies | `orchestrator/auth/dependencies.py` — get_current_user, require_role |
| Auth models (ORM) | `orchestrator/auth/models.py` — User, RefreshToken, ApiKey |
| Auth service | `orchestrator/auth/service.py` — JWT, bcrypt, CRUD |
| DB session | `orchestrator/db/session.py` — init_engine, init_db, get_session_factory |
| Table prefix | `orchestrator/db/base.py` — configure_table_prefix, prefixed, fk |
| Job store (persistence) | `orchestrator/store/base.py` (интерфейс), `store/job_store.py` (memory), `store/sql_job_store.py` (SQL) |
| Alembic-миграции | `alembic/versions/` — `alembic upgrade head` / `alembic revision --autogenerate -m "..."` |
| Access-лог / request_id | `orchestrator/main.py` — `access_log_middleware`, `orchestrator/core/net.py` — `resolve_client_ip` |
| Audit trail | `orchestrator/audit/models.py` (`AuditLog`), `audit/service.py` (`record`, `git_author`), `api/audit.py` (`GET /audit-log`) |
| Audit Log UI | `ui/src/views/AuditLog.vue` (фильтры+пагинация), кнопка **Audit** на строках Workflows/Actions/Connectors/Jobs/ApiKeys (query-параметры `resource_type`/`resource_id`) |
| Пользователи: bootstrap первого admin'а | `python -m orchestrator.auth.cli {create-user,deactivate-user,activate-user} --username X [--role admin]` |
| Пользователи: управление через API/UI | `orchestrator/auth/router.py` (`/auth/users` POST/GET/PATCH), `ui/src/views/Users.vue` |
| Конфиг | `orchestrator/config.py`, `orchestrator/config.yaml` |
| UI | `ui/src/views/` — Status, Workflows, Jobs, JobDetail, Actions, Connectors, AuditLog, ApiKeys, Users, Prompts, Tools, Generate, Settings, Login, Logs |
| UI: права по роли | `ui/src/permissions.js` (`can(role, cap)` — зеркало ролевых кортежей `orchestrator/api/*.py`), `ui/src/router-guard.js` (закрывает прямой переход по URL, не только пункт меню) |
| UI: история/diff/restore | `ui/src/components/HistoryPanel.vue` — общий компонент для workflow/action/connector(code+config), вкладка рядом с редактором |
| Deploy (QA-стенд) | `deploy/stage/` — docker-compose.yml (build:), Dockerfiles |
| Deploy (дистрибуция, air-gap) | `deploy/prod/` (docker-compose.yml с `image:`, config.yaml.template) + `deploy/soarctl`/`soarctl_lib/` — package/install/init/up/migrate/users/backup/doctor/content, см. `docs/compose/specs/2026-07-22-deploy-cli-design.md`. Базовый контентпак коннекторов копируется в образ на сборке (`COPY --from=basepack`, требует sibling-репозиторий `soar-content-pack` как extra build context — Фаза 3, см. `docs/compose/reports/content-as-contentpack.md`); реальной сборкой (`docker compose -f deploy/stage/docker-compose.yml build`) и живым контейнером проверено — все 24 коннектора корректно устанавливаются `seed_connector_pack()` и импортируются из `content-venv`, см. addendum в отчёте |
| Deploy (дистрибуция, on-site/с интернетом) | `soarctl install --repo <url-or-path> [--ref REF]` — сборка образов на месте, без bundle; `soarctl init --interactive`/`--cors-origin` — заполняет `auth.cors_origins` вместо плейсхолдера; `soarctl update [--ref REF] [--migrate fresh\|upgrade]` — git pull/checkout + пересборка + `up`, без `down`, postgres/redis не пересоздаются; `soarctl_lib/git_source.py`, `prompts.py`; см. `docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md` |
| Тесты | `tests/orchestrator/`, `tests/soar/`, `tests/deploy/` — тесты конкретных встроенных коннекторов переехали в `soar-content-pack/tests/` вместе с их кодом (Фаза 3); здесь остаётся платформенная механика (`ConnectorRegistry`, `ConnectorProxy`, pack install pipeline) |
| API endpoints (полные таблицы) | `docs/agents/api-reference.md` |
| Security patterns (полное описание) | `docs/agents/security-patterns.md` |
| Known limitations (полное описание) | `docs/agents/known-limitations.md` |
| Концепты верхнего уровня (карта проблем + реестр рисков, не спеки) | `docs/concepts/` — `UPGRADE.md` (Agent Dev-Loop, этапы 1-3 реализованы), `UPGRADE-v2.md` (pre-release ревью перед деплоем на живую инфру) |
| Queue/Database backend config (полное описание) | `docs/agents/config-reference.md` |
| История версий | `CHANGELOG.md` |

## Rules

### Spec-driven workflow

**Перед началом любой задачи — написать спек.** Без спека не писать код.

1. **Spec** (`docs/compose/specs/YYYY-MM-DD-<feature>-design.md`) — дизайн: проблема, решение, архитектура, интерфейсы. Секции `[S1]`, `[S2]`, ... Без checkbox-ов.
2. **Plan** (`docs/compose/plans/YYYY-MM-DD-<feature>.md`) — пошаговый план с `- [ ]` checkbox-ами, точный код, test-first (сначала падающий тест, потом фикс).
3. **Report** (`docs/compose/reports/<feature>.md`) — frontmatter + что сделано, что изменилось, верификация. Пишется после выполнения.

**AGENTS.md отражает фактическое состояние** — обновляется после каждой итерации, не заранее.

### Архитектурный принцип: движок vs поведение

SOAR — движок (orchestrator: очередь/воркеры/планировщик + registries), а не
набор зашитых интеграций. Поведение системы — что вызывается, с какими
параметрами, по какой политике — обязано быть редактируемым через
API (UI или LLM-агентом) **без передеплоя**. Три штатных места для поведения,
у каждого есть API редактирования с git auto-commit:

- **Интеграционные настройки** (endpoint-ы, пути, TTL, пороги, имена
  connector/workflow) → `connectors/{name}/{name}.yml` (per-instance config,
  `GET/PUT /connectors/{name}/config`). Не создавать отдельные
  config-loader'ы, парсящие `SOAR_CONFIG` или произвольные секции
  `orchestrator/config.yaml` в обход этого API
- **Код, переиспользуемый между несколькими workflow** → `soar/actions/`
  (`GET/PUT /actions/{name}`), не приватные модули в `soar/tools/`
- **Сама логика workflow** → `soar/workflows/{name}.py`
  (`GET/PUT /workflows/{name}/code`)

Следствия:

- `orchestrator/config.yaml` — только инфраструктура самого оркестратора
  (`workers`, `queue`, `git`, `logging`, `soar.*_dir`, `server`). Никаких
  интеграционных/бизнес-секций (endpoint-ы, пороги, имена workflow
  конкретной интеграции) — у этого файла нет API-ручки, правка = ручной
  доступ к серверу или редеплой
- **`soar/tools/` vs `soar/actions/` — критерий класса.** `tools/` — это
  сложный, но универсальный инфраструктурный код в виде класса, не
  завязанный на конкретную интеграцию: тест — "будет ли класс полезен
  второй, не связанной интеграции без изменения кода, только другими
  параметрами конструктора?". Примеры: `WatermarkStore`/
  `SeenStore` (durable курсор/TTL-дедуп — общий примитив для любого
  polling/webhook-приёмника), `LoggingHttpClient`/`CachingHttpClient`
  (httpx.Client-подклассы — логирование безусловно + TTL-кэш per-domain
  опционален, для threat-intel actions).
  **Универсальности недостаточно — нужна ещё обращённость к рабочему
  потоку.** Контрпример: `OpenAPIGenerator` универсален по OpenAPI, но его
  единственный потребитель — `orchestrator/api/connectors.py`, рантайму он
  не нужен; такому коду место в `orchestrator/core/`, а не в витрине
  инструментов (E5 в `docs/concepts/ENTITY-MODEL.md`)
  `actions/` — всё простое и специфичное для одной интеграции: бизнес-
  правила, decision-логика, магические значения (endpoint-пути, теги,
  имена workflow) — даже если внутри action используется класс из
  `tools/`. Пример: диспетчеризация события во внешнюю систему (кому
  какой workflow триггерить, при каких условиях) — решение specific для
  одной интеграции, не переиспользуется. Если модуль смешивает
  универсальную механику с интеграционными дефолтами (TTL-кэш с
  fallback — универсален, форма конкретной policy и её endpoint — нет)
  — механику оставить в `tools/`, специфику вынести в `actions/`
- **Публичная поверхность `soar/tools/` объявляется явно, а не выводится из
  файловой раскладки.** `soar/tools/__init__.py::TOOL_REGISTRY` — литеральный
  dict (`kind`: `class`/`instance`/`factory`), единственный источник и для
  `__all__`, и для `GET /tools` (`orchestrator/core/introspect.py::parse_tool_registry`,
  AST, без импорта). Публикуется то, что предназначено рабочему потоку, — в
  той форме, в которой поток этим пользуется (для `http_client` это
  `kind: instance`, сконфигурированный синглтон, не класс). Внутренняя
  механика (`_cache.py`/`_net.py` — кэш-бэкенды, SSRF-guard) — в `_`-префиксных
  модулях, никогда не в `TOOL_REGISTRY`, в витрину не попадает
- **Публичный инструмент обязан быть документирован и обнаружим
  через read-only API** (`GET /tools`, `GET /tools/{name}`) — разработчик
  триажа (человек или LLM-агент), пишущий action/workflow, должен узнать
  о доступных примитивах и их сигнатурах не читая исходники. Источник
  доки — module/class/method docstring + сигнатура конструктора и
  публичных методов (интроспекция, не ручной дубль — иначе разъедется с
  кодом). `/tools` — **без PUT/DELETE**: в отличие от `connectors/`,
  `actions/`, `workflows/`, tools не является редактируемым через API
  поведением, это часть движка — правки только кодом и релизом
- Если новому коннектору/workflow нужен параметр — сначала спросить "где
  он должен быть редактируем через API", а не "куда его дописать в yaml"

### Code rules

- НЕ коммитить `orchestrator_state.yaml` — только `config.yaml` и код
- НЕ хранить реальные `*.yml` коннекторов в git — только `*.example.yml`
- НЕ писать бизнес-логику в API роутах — только вызовы JobManager/GitManager
- НЕ обращаться к очереди и приватным полям напрямую из роутов — только через публичные методы
- Все пути через config, без хардкода
- НЕ добавлять `Depends(get_db)` как параметр в `get_current_user` — FastAPI вызовет его даже для JWT-запросов без DB. Создавать сессию лениво через `request.app.state.db_session_factory`
- НЕ использовать passlib — несовместима с bcrypt≥5.0.0. Использовать `import bcrypt` напрямую
- Auth включается только при `auth.secret_key != ""` в config. Без ключа — режим анонимного admin

## Token optimization

1. **Не читай весь файл** — используй `grep` для поиска конкретных строк, `read` с `offset/limit` для нужного блока
2. **Не перечитывай** — если файл уже в контексте, работай с тем что есть
3. **Параллельные операции** — запускай независимые чтения/поиски в одном вызове
4. **Минимальные edits** — точечные замены через `oldString/newString`, не переписывай весь файл
5. **Тесты отдельно** — не запускай `tests/` если правишь один файл, запусти конкретный тест
6. **Grep > Read** — для проверки наличия строки/паттерна используй grep, не read файла целиком
7. **Actor для поиска** — делегируй исследование кодовой базы в explore actor, если нужно найти >3 файлов
8. **Сателлиты по требованию** — `docs/agents/*.md` и `CHANGELOG.md` открывай только когда задача
   реально касается API-контрактов, security-механизмов, known limitations или истории версий —
   не читай их "на всякий случай" при каждой сессии

## Version history

Полная история версий — **[CHANGELOG.md](CHANGELOG.md)**.

Текущая версия: **v0.22** (2026-08-05) — Docs-only: `orchestrator/prompts/
system_prompt.md` (встроенный системный промпт агента, `GET /prompts/system`)
переписан — не обновлялся с v0.15 (2026-07-29), за это время ENTITY-MODEL
Фазы 1-4 (v0.17-v0.20) и редизайн tools (v0.21) увели фактуру промпта в
сторону: §2 называл буквальные пути `soar/connectors/<name>/...` вместо
сконфигурированных директорий (`connectors_dir` и т. п.) после отделения
контента в контентпак; способ импортировать инстанс коннектора в коде
воркфлоу/экшена не был описан вовсе, хотя от него зависит credential
scoping (Фаза 4); `GET /runtime` (Фаза 3) не упоминался; примеры про
`/tools` называли классы, удалённые редизайном (`HttpClient` →
`LoggingHttpClient`/`CachingHttpClient`/`new_client`). Новый §3 "Using a
connector from your code" — обе формы импорта, почему концептная
(`from soar.connectors.<type> import <instance>`) предпочтительна:
падает на импорте вместо `AttributeError` в рантайме джобы, и именно её
статически читает credential scoping. Структура выросла с 7 до 8
разделов; RBAC-граница роли `agent` и dev loop сверены с текущим кодом и
перенесены без содержательных изменений (в список исключённых эндпоинтов
добавлен `POST /connectors/pack/install`, не существовавший на v0.15).
`tests/orchestrator/api/test_prompts_api.py` не задет по конструкции
(проверяет только что файл читается/пишется, не его текст) — 5 passed.
Спек/план/отчёт: `docs/compose/specs/2026-08-05-system-prompt-rewrite-design.md`,
`docs/compose/plans/2026-08-05-system-prompt-rewrite.md`,
`docs/compose/reports/system-prompt-rewrite.md`.

Предыдущая версия: **v0.20** (2026-07-30) — Модель сущностей, Фаза 4:
сужение прав (`docs/concepts/ENTITY-MODEL.md`, слой 3 изоляции).
Завершает весь план `ENTITY-MODEL.md` (Фазы 1–4, v0.17–v0.20, одна сессия).
Credential scoping — всегда включён: `orchestrator/core/introspect.py
::parse_connector_usage` статически (AST, без импорта) находит `from
soar.connectors.<type> import <instance>` на верхнем уровне файла
воркфлоу; `orchestrator/core/subprocess_runner.py::build_scoped_config`
строит по этому списку временный `connectors_dir`-срез (символические
ссылки на нужные `.py`, отфильтрованные `.yml`) и передаёт субпроцессу
временный `SOAR_CONFIG`, не `orchestrator/config.yaml` целиком — JWT-секрет
и `database.url` физически не доезжают до раннера. Воркфлоу без статически
найденных импортов получают пустой `connectors_dir`, не fallback на
полный набор (в репозитории нет примеров старой `connectors.<name>`
registry-формы после Фазы 2). Временный каталог (`WorkflowJob.
scoped_config_dir`, новое поле — заодно чинит `WorkflowMeta.file_path`,
который существовал с Фазы 1, но никогда не заполнялся) удаляется в
`Worker._execute`'s `finally` на всех путях выхода; поле проведено через
`SQLQueue`/`RedisQueue` сериализацию (новая колонка `workflow_jobs.
workflow_file`, миграция `7a1c9e3f5b02`), не только `InMemoryQueue`.
Отдельный UID для раннера + `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_NPROC`
(`jobs.runner_uid`, `None` по умолчанию — опционален, POSIX/Docker-only) —
реализован механизмом, отличным от спека: прямой `os.setuid`/`os.setgid` в
`preexec_fn` не работает от непривилегированного родительского процесса
(`soar`, не root) без `CAP_SETUID` на самом интерпретаторе, что стало бы
более широким привилегированным доступом, чем задумано; вместо этого —
`setpriv --reuid=... --regid=...` обёртка вокруг argv, `setpriv` несёт
файловую capability точечно (`setcap`), rlimits — по-прежнему через
`preexec_fn`. Все границы (config.yaml unreadable, git repo unwritable,
state_dir writable, RLIMIT_AS enforcement) проверены на реальных
Linux-контейнерах через Docker — включая повторную проверку постфактум
против уже собранного `stage-orchestrator` образа (не только
изолированным тестовым harness'ем), см. addendum в отчёте. Не
верифицировано: полный `docker compose up` стенд `deploy/stage` с
`jobs.runner_uid` включённым и реальной джобой через живой API
(осознанно отложено). Спек/план/отчёт:
`docs/compose/specs/2026-07-30-privilege-narrowing-design.md`,
`docs/compose/plans/2026-07-30-privilege-narrowing.md`,
`docs/compose/reports/privilege-narrowing.md`.

Предыдущая версия: **v0.19** (2026-07-30) — Модель сущностей, Фаза 3:
контент как контентпак (`docs/concepts/ENTITY-MODEL.md`). Все 24
встроенных коннектора переехали из `soar/connectors/<name>/` в отдельный
локальный git-репозиторий-сиблинг `soar-content-pack` (без remote) —
`soar/connectors/` содержит только `__init__.py`/`base.py`/`_proxy.py`,
структурный дубль (**E1**) устранён физически. Общий install-пайплайн
(`orchestrator/core/pack_install.py`: чтение манифеста, проверка
`runtime_version`/зависимостей против `soar/runtime_contract.py::CONTRACT`,
sha256-маркер происхождения `.soar-content.yaml`, план/применение с
защитой изменённых пользователем коннекторов от перезаписи) используется
тремя путями: `soarctl content install|list|remove`
(`deploy/soarctl_lib/content.py`, alpine tar-pipe в `soar-data` volume, тот
же паттерн, что `backup.py`), `POST /connectors/pack/install`
(`orchestrator/api/packs.py`, admin-only, conflict-preflight+`force`,
аудит), и идемпотентный сидинг на каждом старте оркестратора
(`orchestrator/main.py::seed_connector_pack` вместо однократного
`shutil.copytree` — закрывает **E4**, обновления теперь доезжают до
существующих инсталляций через `soarctl update`). Манифест пака
генерируется AST-скриптом (`soar-content-pack/tools/gen_manifest.py`), не
пишется руками. Обе Dockerfile получили `COPY --from=basepack` из
sibling-репозитория как extra build context — проверено реальной сборкой
(`docker compose build`) и живым контейнером: все 24 коннектора корректно
ставятся `seed_connector_pack()` и импортируются из `content-venv`. 792
passed (было 894 — ожидаемое падение: 145 тестов коннекторов переехали
вместе с кодом в `soar-content-pack/tests/`), `ruff check` чист от новых
находок. Спек/план/отчёт:
`docs/compose/specs/2026-07-30-content-as-contentpack-design.md`,
`docs/compose/plans/2026-07-30-content-as-contentpack.md`,
`docs/compose/reports/content-as-contentpack.md`.

Предыдущая версия: **v0.18** (2026-07-30) — Модель сущностей, Фаза 2:
модель сущностей в коде (`docs/concepts/ENTITY-MODEL.md`, E6+E3 одним
заходом по решению 4). `ConnectorRegistry` — пространство имён по типу
(`dict[type][instance]` вместо плоского словаря, закрывает **E8**),
детерминированный выбор класса при discovery (`obj.__module__ == fqn`,
симметрично `WorkflowRegistry`). `ConnectorProxy` (`soar/connectors/
_proxy.py`) — единственный способ получить коннектор что через
`connectors.<name>` (обратная совместимость), что через новый ленивый шим
`from soar.connectors.<type> import <instance>` (закрывает **E6**) — оба
фасада отдают обёрнутый объект, прямой импорт не может стать дырой в обход
логирования. Каждый публичный вызов метода пишет `SOAR_AUDIT_EVENT` в лог
джобы (редакция `HIDDEN_FIELDS`, длительность, исход); `context["dry_run"]`
блокирует методы, объявленные в новом `MUTATING_METHODS` на коннекторе,
централизованно на прокси, не по добровольному соглашению воркфлоу;
`Worker._execute` парсит эти строки в `AuditLog` (закрывает часть **E3** —
что джоба сделала во внешней системе, теперь видно). `soar/actions/
__init__.py` регистрирует все public top-level callables модуля, не только
одноимённый с файлом; `GET /actions` — AST-only (не импортирует контент из
процесса оркестратора, требование Фазы 1) и отражает ровно то, что реестр
исполнит (закрывает **E7**). `soar/tools/__init__.py::__all__` —
единственный источник того, что видно `GET /tools`; `OpenAPIGenerator`
переехал в `orchestrator/core/` (не инструмент рантайма), `watermark_store`/
`seen_store` — фабрики по образцу `http_client` (закрывает **E5**).
Оставшиеся 7 `requests`/`httpx`-коннекторов (`censys`/`crtsh`/`fofa`/
`freeipa`/`security_onion`/`urlhaus`/`wazuh`) мигрированы на
`http_client_sync`. 894 passed (было 808), `ruff check` чист от новых
находок. Спек/план/отчёт:
`docs/compose/specs/2026-07-30-entity-model-in-code-design.md`,
`docs/compose/plans/2026-07-30-entity-model-in-code.md`,
`docs/compose/reports/entity-model-in-code.md`.

Предыдущая версия: **v0.17** (2026-07-30) — Модель сущностей, Фаза 1:
граница исполнения (`docs/concepts/ENTITY-MODEL.md`). Два venv в образе —
`platform-venv` (`orchestrator/requirements.txt`, первый на `PATH`) и
`content-venv` (`soar/requirements.txt`, реально устанавливается впервые —
закрывает **E2**, 11 из 24 встроенных коннекторов не хватало пакетов);
`SubprocessRunner` запускает воркфлоу через `content-venv`
(`SOAR_CONTENT_PYTHON`, fallback на `sys.executable` вне Docker/тестов).
`soar/runtime_contract.py` — версионированный контракт зависимостей (имя
для импорта + протокол/вендор), единственный источник и для установки, и
для `GET /runtime` (новая ручка — окружение по API, пакеты по имени
импорта, guaranteed/present_not_guaranteed, закрывает **E9**).
`orchestrator/main.py::load_workflow_metas` больше не импортирует
пользовательский код воркфлоу — AST-парсинг (`orchestrator/core/
introspect.py::parse_workflow_meta`), закрывает **E10.3**, обязательное
условие после разделения рантаймов, а не только гигиена. Аудит-хук
(`soar/audit_hook.py`, `sys.addaudithook`) ставится в `soar/runner.py` до
любого `init()` — наблюдает и блокирует egress на приватные адреса
независимо от библиотеки; существующий SSRF-guard в `http_client.py` не
тронут (остаётся pre-flight-проверкой, хук — платформенная гарантия
сверху). Реальная сборка + прогон в Docker нашли и закрыли два дефекта,
невидимых юнит-тестам: `httpx` отсутствовал в `orchestrator/
requirements.txt` (транзитивная зависимость через `soar.tools.openapi`), и
`GET /runtime` резолвил символическую ссылку `content-venv/bin/python` до
системного интерпретатора (`.resolve()` → `.absolute()`). 811 passed
(было 780), `ruff check` чист от новых находок. Спек/план/отчёт:
`docs/compose/specs/2026-07-30-runtime-boundary-design.md`,
`docs/compose/plans/2026-07-30-runtime-boundary.md`,
`docs/compose/reports/runtime-boundary.md`.

Предыдущая версия: **v0.16** (2026-07-29) — `soarctl` on-site: checkout — это
инстанс, без промежуточной директории. Реворк
`docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md` — та версия
оставляла `install --repo`/`update` копировать `docker-compose.yml`/
`config.yaml.template` в отдельно названную `--dir`-директорию, никак
структурно не связанную с чекаутом (и не копировала туда сам `soarctl` —
задокументированный в README шаг `cd soar-prod && python soarctl doctor`
падал бы с "file not found", не был проверен end-to-end). Теперь
`git_source.install(checkout, ref)` пишет `VERSION`/`source.json` прямо в
`<checkout>/deploy/prod/` (файлы уже там, в git — копировать нечего);
`--repo <url>` (клонирование самим `soarctl`) убрано целиком — пользователь
клонирует сам, `soarctl` работает только с уже существующим чекаутом.
`paths.instance_dir()` теперь ищет рабочую директорию вверх от cwd тем же
способом, что `git` ищет `.git` — `docker-compose.yml` напрямую (bundle) или
`pyproject.toml` + `deploy/prod/docker-compose.yml` (on-site) — поэтому
любая подкоманда работает из любой поддиректории чекаута, не только из его
корня. Новый `./soarctl` — bash-обёртка в корне репозитория
(`git update-index --chmod=+x`, `.gitattributes` фиксирует LF), убирает
префикс `python deploy/soarctl`. Итоговый флоу: `git clone <url> soar && cd
soar && ./soarctl install && ./soarctl init && ./soarctl up`. Air-gap
bundle-путь (`package`/`install <bundle.tar.gz>`) не тронут. 115 тестов в
`tests/deploy/` (было 106 — новые/переписанные вокруг `instance_dir()`,
`git_source.install()`, `cli.py`), `ruff check` без находок. Спек/план/отчёт:
`docs/compose/specs/2026-07-29-soarctl-inplace-onsite-design.md`,
`docs/compose/plans/2026-07-29-soarctl-inplace-onsite.md`,
`docs/compose/reports/soarctl-inplace-onsite.md`.

Предыдущая версия: **v0.15** (2026-07-29) — Docs-only: `orchestrator/prompts/
system_prompt.md` (встроенный системный промпт агента, `GET
/prompts/system`) не обновлялся с Этапа 2 Agent Dev-Loop (2026-07-22) и
содержал устаревшее/неверное утверждение, будто `GET
/connectors/{name}/config` отдаёт секреты в открытом виде — на самом деле
с v0.12 они маскируются `"********"` для всех ролей включая `admin`.
Добавлена секция про фактические права роли `agent` (код+jobs, не
администрирование; `PUT /connectors/{name}/code` — единственное
write-исключение, литеральный `admin`, B3), переписан раздел про секреты
коннекторов на актуальное поведение (write-only, merge-on-write,
`"********"` — не значение), и `Tool` (`soar/tools/`) добавлен в список
сущностей как явно read-only (без PUT/DELETE ни для одной роли) — раньше
упоминался только в разделе self-description, не был назван как сущность.
Спек/план/отчёт:
`docs/compose/{specs,plans,reports}/2026-07-29-system-prompt-refresh*`.

Предыдущая версия: **v0.14** (2026-07-28) — `docs/concepts/BAGFIX_PLAN.md` закрыт
целиком: все 4 блокера пилота (B1-B4), все 8 существенных пункта (S1-S8),
все 8 расхождений документации (D1-D8) из pre-production ревью
2026-07-27. Кратко: деактивация пользователя реально отзывает refresh-токены
(B1); `/config/diff` больше не палит секреты через контекстные строки diff'а
(B2); `agent` больше не может обнулить `HIDDEN_FIELDS` коннектора, переписав
код (B3); `server.trusted_proxies` заведён для nginx-деплоя — rate-limit и
`AuditLog.client_ip` больше не общие на весь трафик (B4); `SyncHttpClient` —
синхронный `HttpClient` для коннекторов, 3 TI-коннектора мигрированы как
образец (S1); порядок инициализации `soar/runner.py` починен — `http_client`
конфигурируется до импорта пользовательского кода (S2); `/transfer/export`
и `/import` редактируют секреты, пишут audit, валидируют и коммитят код
(S3); `POST /jobs`/`POST /webhooks/{name}` пишут `job.create` в audit-лог
(S4); `purge_old()` чистит файлы логов вместе со строками БД (S5);
партиальный индекс `workflow_jobs` гарантирован на любой инсталляции,
миграции уважают `table_prefix` (S6); тест-сьют полностью зелёный (S7);
новые коннекторы получают `HIDDEN_FIELDS` по умолчанию, вручную и через
генератор (S8). Каждый пункт — отдельный цикл спека→план→отчёт, в
изолированной git-ветке, смерджен после прогона тестов. Полный набор:
756 passed, 1 skipped (преэкзистентный, не связан). См.
`docs/concepts/BAGFIX_PLAN.md`, `docs/compose/specs/2026-07-28-*-design.md`,
отчёты — `docs/compose/reports/{auth-deactivation-revocation,
connector-diff-redaction-fix,connector-code-agent-lockdown,trusted-proxies,
http-client-sync-facade,http-client-init-order,
transfer-export-import-hardening,job-webhook-audit-logging,job-log-purge,
workflow-jobs-index-table-prefix,test-suite-green,
new-connector-hidden-fields-default}.md`.

Предыдущая версия: **v0.13** (2026-07-27) — `soarctl` on-site install + update:
`soarctl install --repo <url-or-path> [--ref REF]` собирает образы локально
из git-чекаута вместо air-gap bundle (`docker load`), переиспользуя
`bundle.build_images()`; `soarctl init --interactive`/`--cors-origin` заводит
реальный `auth.cors_origins` через `${CORS_ORIGINS_JSON}` в
`config.yaml.template` вместо ручного пост-редактирования — частичное
закрытие P17 кодом поверх чеклиста; `soarctl update [--ref REF] [--migrate
fresh|upgrade]` — git fetch/checkout+pull, пересборка, `env.update_version()`,
`compose up` без `down`, postgres/redis не пересоздаются (теги их образов не
меняются); `soarctl doctor` — новая проверка `git checkout` для
git-инстансов. Только для `deploy/prod`, air-gap bundle-путь не затронут. См.
`docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md`, отчёт —
`docs/compose/reports/soarctl-onsite-update.md`.

Предыдущая версия: **v0.12** (2026-07-27) — pre-release ревью перед деплоем на живую
инфраструктуру (`docs/concepts/UPGRADE-v2.md`, P12/P13/P14/P16): `HttpClient`
(`soar/tools/http_client.py`, безусловное логирование + опциональный кэш +
SSRF-guard) для threat-intel actions; connector config schema + редакция
секретов (`HIDDEN_FIELDS` на всех 24 коннекторах, `GET /connectors/{name}/schema`,
маскирование hidden-полей в config/history/diff для всех ролей включая admin,
merge-on-write + admin-only смена реального значения); `SQLQueue` — poll-based
очередь поверх `workflow_jobs`, устраняет at-most-once потерю джобов
`RedisQueue`, дефолт в `deploy/prod`/`deploy/stage`, + `jobs.retention_days`
(периодическая очистка через `OrchestratorScheduler`); `GitManager.commit()` —
детерминированное определение "нечего коммитить" через `git diff --cached
--quiet` вместо string-match по stderr (закрывает потерю audit-записи при
untracked-файлах). P15/P17 — приняты как есть (recovery через CLI / чеклист
деплоя), без изменений кода. Отчёты: `docs/compose/reports/{http-client,
connector-secrets-schema,sql-job-queue,git-manager-nothing-to-commit}.md`.
