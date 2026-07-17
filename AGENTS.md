# AGENTS.md — SOAR Project v0.7

## What is this

SOAR (Security Orchestration, Automation and Response) — система автоматизации инцидентов. Три компонента:

1. **`soar/`** — Python-пакет: enterprise-коннекторы (SSH, AD, FreeIPA, Elastic, SecurityOnion, Wazuh, PostgreSQL/MySQL/MSSQL, Telegram, SMTP, VirusTotal, Abuse.ch, File, WinRM, SMB, Shodan, Fofa, Censys, MISP, RstCloud, Kaspersky OpenTip, URLhaus, crt.sh), actions, workflows, реестры
2. **`orchestrator/`** — FastAPI сервис: очередь задач, воркеры, планировщик, git-версионирование
3. **`ui/`** — Vue.js SPA: **заглушка для ручного тестирования, не часть продукта**. Основной API-доступ — напрямую на порту 8000 (orchestrator). UI нужен только для визуальной проверки workflows/actions/connectors в браузере

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

# Stage deploy (Docker)
cd deploy/stage && docker compose up --build
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
│   ├── queue/                 # AbstractJobQueue → InMemoryQueue | RedisQueue
│   ├── worker.py              # Worker — один воркер, цикл pop → execute
│   ├── worker_pool.py         # WorkerPool — N воркеров как asyncio tasks
│   ├── scheduler.py           # OrchestratorScheduler (APScheduler)
│   ├── job_manager.py         # JobManager — координатор, enqueue/cancel
│   ├── subprocess_runner.py   # Запуск workflows как subprocess
│   └── git_manager.py         # Git операции через subprocess
├── store/
│   ├── base.py                 # AbstractJobStore — интерфейс (save/get/list/count_by_status/stats/recover_on_startup)
│   ├── job_store.py            # InMemoryJobStore (JobStore — алиас для обратной совместимости)
│   ├── models.py                # SQLAlchemy ORM: JobRecord (workflow_jobs)
│   └── sql_job_store.py        # SQLJobStore — персистентный джоб-стор поверх database.url
├── auth/
│   ├── __init__.py
│   ├── models.py              # SQLAlchemy ORM: User, RefreshToken, ApiKey
│   ├── schemas.py             # Pydantic v2: LoginRequest, TokenResponse, UserOut, ApiKeyOut, ApiKeyCreated
│   ├── service.py             # JWT create/decode, bcrypt hash/verify, CRUD пользователей/ключей
│   ├── dependencies.py        # get_current_user (lazy DB), require_role(), CurrentUser dataclass
│   ├── router.py              # /auth/* endpoints (login, refresh, logout, me, keys)
│   └── cli.py                 # python -m orchestrator.auth.cli create-user
├── db/
│   ├── __init__.py
│   ├── base.py                # DeclarativeBase, configure_table_prefix()/prefixed()/fk() — table prefix
│   └── session.py             # init_engine, init_db (create_all), get_db, get_session_factory
└── api/
    ├── workflows.py           # GET/POST enable/disable, reload + CRUD кода workflow
    ├── actions.py             # CRUD actions + templates
    ├── connectors.py          # CRUD connectors + code/config + OpenAPI generate/preview
    ├── jobs.py                # POST запуск, GET статус, cancel
    ├── webhooks.py            # POST webhook с токеном
    ├── logs.py                # GET лог + SSE стрим
    ├── status.py              # GET /status — воркеры, очередь, статистика
    ├── transfer.py            # POST export/import — импорт/экспорт конфигурации
    ├── tools.py               # GET /tools — read-only discovery (AST, без импорта) для soar/tools/
    └── validation.py          # validate_name, validate_path_within, SSRF validation

soar/
├── __init__.py                # Экспорт connectors, actions, workflows
├── logger.py                  # setup_logging(), get_logger()
├── runner.py                  # Точка входа для subprocess workflows
├── connectors/
│   ├── __init__.py            # ConnectorRegistry — автообнаружение коннекторов
│   ├── base.py                # BaseConnector (lazy connect)
│   ├── ssh/                   # SSHConnector — exec_command, put_file, get_file, list_dir
│   ├── active_directory/      # ActiveDirectoryConnector — search, get_user, authenticate, modify
│   ├── freeipa/               # FreeIPAConnector — user/group/host CRUD, hbac, certs
│   ├── elastic/               # ElasticConnector — query, index, bulk, indices, ILM
│   ├── security_onion/        # SecurityOnionConnector — alerts, events, agents, hunts, pcap
│   ├── wazuh/                 # WazuhConnector — agents, alerts, sca, vulns, syscheck, rules
│   ├── postgresql/            # PostgreSQLConnector — execute, tables, columns
│   ├── mysql/                 # MySQLConnector — execute, tables, columns
│   ├── mssql/                 # MSSQLConnector — execute, tables, columns
│   ├── winrm/                 # WinRMConnector — exec_command, run_ps, upload/download
│   ├── smb_rpc/               # SmbRpcConnector — SMB/RPC file operations
│   ├── telegram/              # TelegramConnector — send_message/photo/document, get_updates
│   ├── smtp/                  # SMTPConnector — send_email/text/html with attachments
│   ├── virus_total/           # VirusTotalConnector — IP/domain/file/URL reports, upload
│   ├── abusech/               # AbuseChConnector — ThreatFox IOCs, MalwareBazaar, URLhaus
│   ├── shodan/                # ShodanConnector — search hosts, DNS resolve/reverse
│   ├── censys/                # CensysConnector — hosts/certificates search
│   ├── fofa/                  # FofaConnector — host search, user info
│   ├── misp/                  # MispConnector — events/attributes/sightings CRUD
│   ├── rstcloud/              # RstCloudConnector — IP/domain/hash/URL checks
│   ├── kaspersky_opentip/     # KasperskyOpenTipConnector — IP/domain/hash/URL checks
│   ├── urlhaus/               # UrlhausConnector — URL/host/payload lookups
│   ├── crtsh/                 # CrtshConnector — certificate/domain/identity search
│   └── file/                  # FileConnector — write/read/append/delete файлы
├── actions/
│   └── __init__.py            # ActionsRegistry — автообнаружение actions
├── workflows/
│   ├── __init__.py            # WorkflowRegistry — автообнаружение workflows
│   └── base.py                # BaseWorkflow, ScheduledWorkflow, WebhookWorkflow, ManualWorkflow
├── tools/
│   ├── openapi.py              # OpenAPIGenerator — генератор коннектора из OpenAPI-спеки
│   └── watermark.py             # WatermarkStore/SeenStore — durable курсор / TTL-дедуп (generic)
└── examples/
    └── nadproject_integration.py

ui/src/
├── main.js                    # Router
├── App.vue                    # Навигация
├── api.js                     # API клиент
└── views/
    ├── Status.vue             # Dashboard
    ├── Workflows.vue          # Управление workflows (enable/disable/edit/run)
    ├── Jobs.vue               # Мониторинг jobs
    ├── Actions.vue            # Управление actions (edit/create)
    └── Connectors.vue         # Управление коннекторами (code/config)

alembic/                      # Alembic-миграции (auth + workflow_jobs таблицы), см. Database backend
├── env.py                    # читает config.yaml (SOAR_CONFIG), применяет table_prefix перед импортом моделей
└── versions/
    └── ..._initial_auth_and_jobs_tables.py

deploy/stage/
├── docker-compose.yml         # orchestrator :8000 + UI :3000 (nginx proxy) + redis + postgres
├── Dockerfile.orchestrator    # Python 3.11 + git + deps + alembic/
├── Dockerfile.ui              # Node build → nginx
├── nginx.conf                 # proxy /api, /docs, /openapi.json → orchestrator:8000
├── config.yaml                # Stage defaults (Postgres + table_prefix + jobs.persistence: sql)
├── Makefile                   # make up/down/build/logs/migrate
└── README.md

tests/
├── soar/                      # flat files: test_<connector>_connector.py (mocked),
│   │                          #   test_workflows.py, test_workflow_registry_naming.py,
│   │                          #   test_base_connector*.py
│   └── tools/                 # OpenAPI generator tests
└── orchestrator/
    ├── api/                   # API route tests
    ├── store/                 # AbstractJobStore contract, SQLJobStore (sqlite in-memory)
    ├── test_job_manager.py    # enqueue, concurrency policies, cancel
    ├── test_job_store.py      # InMemoryJobStore: store, eviction, recover_on_startup
    ├── test_table_prefix.py   # table_prefix applied at model-import time (subprocess-isolated)
    ├── test_alembic_schema.py # alembic upgrade head matches Base.metadata (subprocess)
    ├── test_worker.py         # execute, timeout, QUEUE wait, crash recovery
    ├── test_scheduler.py      # scheduled triggers
    ├── test_queue.py          # InMemoryQueue + RedisQueue (mocked)
    └── ...                    # config, git_manager, models, worker_pool, subprocess env
```

## API Endpoints

### Workflows
| Method | Path | Description |
|--------|------|-------------|
| GET | /workflows | Список registered workflows (runtime meta) |
| GET | /workflows/{name} | Получить meta workflow |
| POST | /workflows/{name}/enable | Включить workflow |
| POST | /workflows/{name}/disable | Выключить workflow |
| POST | /workflows/reload | Перечитать файлы и обновить job_manager |
| POST | /workflows/scheduler/reload | Пересоздать jobs планировщика из текущих metas |
| GET | /workflows/{name}/code | Получить код workflow |
| PUT | /workflows/{name}/code | Сохранить код workflow |
| DELETE | /workflows/{name}/code | Удалить файл workflow |
| GET | /workflows/code/template | Шаблон workflow |

### Actions
| Method | Path | Description |
|--------|------|-------------|
| GET | /actions | Список actions |
| GET | /actions/template | Шаблон boilerplate |
| GET | /actions/{name} | Получить код |
| GET | /actions/{name}/code | Получить код (алиас) |
| PUT | /actions/{name} | Сохранить код |
| DELETE | /actions/{name} | Удалить action |

### Connectors
| Method | Path | Description |
|--------|------|-------------|
| GET | /connectors | Список коннекторов |
| GET | /connectors/template | Шаблон кода + конфига |
| GET | /connectors/{name} | Meta коннектора (class_name, has_code, has_config) |
| POST | /connectors/{name} | Создать коннектор |
| DELETE | /connectors/{name} | Удалить коннектор |
| GET | /connectors/{name}/code | Получить код .py |
| PUT | /connectors/{name}/code | Сохранить код .py |
| GET | /connectors/{name}/config | Получить конфиг .yml |
| PUT | /connectors/{name}/config | Сохранить конфиг .yml |
| POST | /connectors/generate | Генерация коннектора из OpenAPI spec |
| POST | /connectors/preview | Парсинг OpenAPI spec (POST, тело) |
| GET | /connectors/preview | Парсинг OpenAPI spec (GET, URL) — SSRF-защищён |

### Tools

| Method | Path | Description |
|--------|------|-------------|
| GET | /tools | Список классов `soar/tools/` (name, module, summary) — AST, без импорта |
| GET | /tools/{name} | Докстринг, сигнатура конструктора и публичных методов класса |

### Transfer
| Method | Path | Description |
|--------|------|-------------|
| POST | /transfer/export | Экспорт конфигурации в ZIP |
| POST | /transfer/import | Импорт конфигурации из ZIP |

### Jobs
| Method | Path | Description |
|--------|------|-------------|
| POST | /jobs | Запустить workflow |
| GET | /jobs | Список jobs |
| GET | /jobs/{id} | Статус job |
| POST | /jobs/{id}/cancel | Отменить job |

### Webhooks
| Method | Path | Description |
|--------|------|-------------|
| POST | /webhooks/{workflow_name} | Отправить webhook |

### Logs
| Method | Path | Description |
|--------|------|-------------|
| GET | /logs/{job_id} | Получить лог |
| GET | /logs/{job_id}/stream | SSE стрим лога |

### Status
| Method | Path | Description |
|--------|------|-------------|
| GET | /status | Воркеры, очередь, статистика |

### Auth
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| POST | /auth/login | — | Логин (username + password) → access_token + refresh_token |
| POST | /auth/refresh | — | Ротация refresh_token → новый access_token |
| POST | /auth/logout | любой | Отзыв refresh_token |
| GET | /auth/me | любой | Текущий пользователь |
| POST | /auth/keys | admin | Создать API-ключ (возвращается один раз) |
| GET | /auth/keys | admin | Список API-ключей |
| DELETE | /auth/keys/{key_id} | admin | Удалить API-ключ |

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

### Git auto-commit
Любое изменение файла через API автоматически коммитится в git.

### Subprocess execution
Workflows запускаются как отдельные процессы через `soar.runner`:
- stdout перенаправляется в файл лога
- Контекст передаётся через env vars (SOAR_CONTEXT)
- Actions и connectors инициализируются в subprocess

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

**Exit codes:** `0` = success, `1` = failure (stdout JSON still required)

**Do not change this contract** without updating `SubprocessRunner` and tests simultaneously.

### Queue backend
Очередь задач поддерживает два бэкенда:

**In-Memory (по умолчанию)**:
```yaml
queue:
  backend: memory
```

**Redis**:
```yaml
queue:
  backend: redis
  redis_url: redis://redis:6379/0
  redis_max_connections: 10
  redis_push_timeout: 5.0
  redis_pop_timeout: 1.0
```

RedisQueue (`orchestrator/core/queue/redis_queue.py`):
- Connection pooling через `aioredis.from_url()`
- Автоматическое переподключение при ошибках соединения
- Таймауты для push/pop операций
- Health check через `/status` endpoint (`connected: true/false`)

### Database backend (SQLite/PostgreSQL) и table prefix

Один общий `database:` конфиг используется и auth-таблицами (`users`,
`refresh_tokens`, `api_keys`), и (опционально) job-историей — переключение
SQLite/Postgres задаётся только через `database.url`, отдельного флага
backend нет:

```yaml
database:
  url: sqlite+aiosqlite:///./soar.db   # или postgresql+asyncpg://user:pass@host:5432/dbname
  pool_size: 10                         # игнорируется для sqlite
  max_overflow: 20                      # игнорируется для sqlite
  table_prefix: ""                      # напр. "stage_" — см. ниже
```

**table_prefix** — префикс имён таблиц (`^[a-zA-Z0-9_]*$`), чтобы несколько
инстансов SOAR могли шарить одну физическую БД без конфликтов имён. Применяется
через `orchestrator/db/base.py::configure_table_prefix()` — **обязан** быть
вызван до первого импорта `orchestrator.auth.models` / `orchestrator.store.models`,
т.к. `__tablename__` фиксируется при определении класса (импорте модуля), а не
в рантайме. `orchestrator/main.py` вызывает `configure_table_prefix()` в самом
начале файла, до всех остальных `orchestrator.*` импортов — не переставлять
этот блок вниз. `alembic/env.py` делает то же самое. Префикс фиксирован на
время жизни процесса — горячая замена не поддерживается (требует рестарт).

Каждая новая Alembic-миграция, трогающая эти таблицы, обязана использовать
`prefixed("table_name")`/`fk("table", "column")` вместо литеральных строк —
иначе префикс не применится к именам индексов/constraint'ов, что вызовет
коллизии при нескольких инстансах на одной БД (Postgres требует уникальности
имён индексов в пределах схемы, не таблицы).

**Job persistence** (`jobs.persistence`) — независимый переключатель, не
привязан к `database.url` напрямую (используется, только если `sql`):

```yaml
jobs:
  persistence: memory   # по умолчанию — InMemoryJobStore, ничего не меняется
  # persistence: sql    # SQLJobStore поверх database.url — переживает рестарт контейнера
```

`InMemoryJobStore`/`SQLJobStore` реализуют общий `AbstractJobStore`
(`orchestrator/store/base.py`) — `JobManager`/`Worker`/`WorkerPool` работают
с любым из них через публичный интерфейс, без изменений на вызывающей
стороне.

**Alembic** — единственный источник схемы для новых изменений в продакшне.
`init_db()` (`create_all()`) по-прежнему выполняется на каждом старте
сервиса — но он только создаёт отсутствующие таблицы, никогда не меняет уже
существующие (не добавит новую колонку и т.п.), так что реальные будущие
миграции идут исключительно через Alembic:

```bash
alembic revision --autogenerate -m "<message>"     # сгенерировать новую миграцию
alembic upgrade head                               # применить миграции
```

**Важно (проверено на реальном Postgres в deploy/stage):** на первом
деплое `create_all()` уже создаёт таблицы текущей головной ревизии до того,
как оператор успевает вызвать Alembic — `alembic upgrade head` в этом
случае упадёт с `DuplicateTableError`, т.к. пытается создать уже
существующие таблицы. Первый запуск на свежей БД — `alembic stamp head`
(помечает БД как смигрированную без повторного выполнения DDL), не
`upgrade head`. `upgrade head` — только для реальных будущих миграций
(добавление колонки и т.п.), когда `create_all()` уже не поможет. См.
`deploy/stage/Makefile` (`make migrate-stamp-initial` / `make migrate`).

`SOAR_CONFIG` (тот же env var, что и у сервиса) определяет, какой
`config.yaml` читает `alembic/env.py` — миграции никогда не расходятся с
конфигом запущенного сервиса.

## Security patterns

### Input validation (orchestrator/api/validation.py)
- `validate_name(name)` — regex `^[a-zA-Z0-9_\-]+$`, блокирует path traversal и shell metacharacters
- `validate_path_within(base, target)` — `normpath + startswith`, предотвращает directory escape
- SSRF protection — блокировка RFC 1918, link-local, localhost, cloud metadata IPs + DNS resolve (socket.getaddrinfo) + follow_redirects=False

### Connector security (soar/connectors/)
- SQL: параметризованные запросы (PostgreSQL, MSSQL) + валидация имён (MySQL)
- LDAP: RFC 4515 escaping спецсимволов (`*`, `(`, `)`, `\`, NUL)
- File: path boundary check через `_resolve()` + `resolve()` + `startswith()`
- SSH: `WarningPolicy()` вместо `AutoAddPolicy()` (MITM protection)
- WinRM: SSL verification по умолчанию (`verify_ssl=True`)
- HTTP: `timeout=30` на все HTTP-запросы (prevents worker pool exhaustion)
- Wazuh: пустые credentials по умолчанию, SSL verification включён

### Authentication (orchestrator/auth/)
- **Auth-disabled mode**: когда `auth.secret_key = ""` — `get_current_user` возвращает анонимного admin. Backward-совместимость с Docker-сетевым доверием и существующими тестами.
- **JWT access tokens** (HS256, TTL 30min): payload `{sub, role, type:"user", exp}`
- **Refresh tokens**: opaque UUID, TTL 7d, хранятся как `SHA-256(token)` в Postgres, ротируются при каждом `/auth/refresh`
- **API keys**: формат `soar_<32-byte-hex>`, хранятся как `SHA-256(key)`, для M2M сервисных аккаунтов
- **RBAC роли**: `admin`, `analyst`, `viewer`, `service`; каждый эндпоинт декорирован `Depends(require_role(...))`
- **Lazy DB session**: `get_current_user` не принимает `Depends(get_db)` — создаёт сессию только когда нужна проверка API-ключа (через `request.app.state.db_session_factory`)
- **bcrypt напрямую**: `import bcrypt` + `bcrypt.hashpw/checkpw` — passlib 1.7.4 несовместима с bcrypt≥5.0.0 (`__about__` был убран)
- **CORS**: `allow_origins=config.auth.cors_origins` + `allow_credentials=True`; `allow_origins=["*"]` несовместим с `credentials=True` в браузерах
- **Дефолтная DB**: `sqlite+aiosqlite:///./soar.db` (создаётся в рабочей директории). В продакшене — `postgresql+asyncpg://...` в `config.yaml`
- **CLI создания пользователя**: `python -m orchestrator.auth.cli create-user --username admin --role admin`

### Rate limiting (orchestrator/main.py)
- In-memory rate limiter: 120 req/60s per IP
- Логин `/auth/login`: строже — 5 req/60s (брутфорс-защита)
- Пропускает localhost/testclient для dev/тестов

### Request body limit
- 5MB максимум для POST/PUT/PATCH

### Subprocess isolation
- `create_subprocess_exec` (argument list, no shell) — prevent command injection
- Environment variable allowlist — предотвращает утечку секретов
- Log-per-job файл с guaranteed cleanup в finally block

### Connector HTTP hardening
- Все HTTP-коннекторы: `timeout=30` на каждый запрос (Abuse.ch, Censys, Crtsh, Fofa, FreeIPA, Kaspersky, RstCloud, SecurityOnion, Urlhaus, Wazuh)
- SSH: `WarningPolicy()` вместо `AutoAddPolicy()` — MITM protection
- WinRM: `verify_ssl=True` по умолчанию, `server_cert_validation="validate"`
- Wazuh: пустые credentials по умолчанию, SSL verification включён, `urllib3` warnings не глушаются

### API hardening
- `DELETE /workflows/{name}/code` — cleanup `orchestrator_state.yaml` перед reload
- `GET /workflows/{name}` и `GET /workflows` — webhook token в response dict
- `POST /jobs` — отдельный 409 для disabled workflow (`WorkflowDisabledError`)
- `POST /transfer/import` — Zip Slip protection (path traversal + `..` check), name validation
- `GET /connectors/preview` — SSRF protection: блокировка internal/private IPs и localhost
- `PUT /connectors/{name}/code` и `config` — UTF-8 validation + null byte check
- Git log history: null-byte delimiter вместо `|` (prevents delimiter injection)
- `CORSMiddleware(allow_credentials=True)` с конкретными origins из `config.auth.cors_origins` (не `"*"`)

## Known limitations

| # | Limitation | Workaround until fixed |
|---|------------|------------------------|
| 1 | **ConcurrencyPolicy.QUEUE** — реализован в Worker как busy-wait: ждущий job занимает воркер целиком; между проверкой "нет RUNNING" и установкой RUNNING есть гонка — два QUEUE-job могут стартовать одновременно | Не полагаться на строгую сериализацию; для критичных workflows использовать FORBID |
| 2 | **RedisQueue may lose messages on connection drop** — at-most-once delivery, no ACK | Use `backend: memory` for critical workflows; Redis only for high-throughput non-critical |
| 3 | **Worker crash recovery работает только при `jobs.persistence: sql`** — на дефолте (`memory`) хранилище in-memory: на старте пустое, recovery фактически no-op | Установить `jobs.persistence: sql` (`database.url` на Postgres/SQLite-файл) для продакшна |
| 4 | **JobStore теряет историю при рестарте только на дефолте `jobs.persistence: memory`** — с `sql` история переживает `docker compose restart` (см. Database backend) | Export jobs before restart if history matters (только для `memory`) |
| 5 | **`keep_completed` eviction** — eviction policy is FIFO by insertion order | Do not rely on old completed jobs being available if throughput is high |

## File map (для быстрого навигации)

| Что нужно | Куда смотреть |
|-----------|---------------|
| Добавить API эндпоинт | `orchestrator/api/*.py` |
| Новый коннектор | `soar/connectors/`, скопировать `elastic/` как шаблон |
| Telegram коннектор | `soar/connectors/telegram/` — send_message, send_photo, send_document, get_updates |
| SMTP коннектор | `soar/connectors/smtp/` — send_email, send_text, send_html (plain/HTML, CC/BCC, вложения) |
| File коннектор | `soar/connectors/file/` — write, write_json, append, read, list_files, delete |
| SSH коннектор | `soar/connectors/ssh/` — exec_command, put_file, get_file, list_dir |
| Active Directory | `soar/connectors/active_directory/` — search, get_user, authenticate, modify |
| FreeIPA | `soar/connectors/freeipa/` — user/group/host CRUD, hbac, certs |
| Elastic | `soar/connectors/elastic/` — query, index, bulk, indices, ILM |
| Security Onion | `soar/connectors/security_onion/` — alerts, events, agents, hunts, pcap |
| Wazuh | `soar/connectors/wazuh/` — agents, alerts, sca, vulns, syscheck, rules |
| PostgreSQL | `soar/connectors/postgresql/` — execute, tables, columns |
| MySQL | `soar/connectors/mysql/` — execute, tables, columns |
| MSSQL | `soar/connectors/mssql/` — execute, tables, columns |
| VirusTotal | `soar/connectors/virus_total/` — IP/domain/file/URL reports, upload |
| Abuse.ch | `soar/connectors/abusech/` — ThreatFox IOCs, MalwareBazaar, URLhaus |
| WinRM | `soar/connectors/winrm/` — exec_command, run_ps, upload/download |
| SMB/RPC | `soar/connectors/smb_rpc/` — SMB/RPC file operations |
| Shodan | `soar/connectors/shodan/` — search hosts, DNS resolve/reverse |
| Fofa | `soar/connectors/fofa/` — host search, user info |
| Censys | `soar/connectors/censys/` — hosts/certificates search |
| MISP | `soar/connectors/misp/` — events/attributes/sightings CRUD |
| RstCloud | `soar/connectors/rstcloud/` — IP/domain/hash/URL checks |
| Kaspersky OpenTip | `soar/connectors/kaspersky_opentip/` — IP/domain/hash/URL checks |
| URLhaus | `soar/connectors/urlhaus/` — URL/host/payload lookups |
| crt.sh | `soar/connectors/crtsh/` — certificate/domain/identity search |
| Watermark / дедуп событий | `soar/tools/watermark.py` — WatermarkStore, SeenStore (durable JSON, generic) |
| Новый action | `soar/actions/`, один файл = одна функция |
| Новый workflow | `soar/workflows/`, наследовать от `ScheduledWorkflow`/`WebhookWorkflow`/`ManualWorkflow` |
| Шаблон workflow | `orchestrator/api/workflows.py` — TEMPLATES dict |
| Изменить модель | `orchestrator/models/` |
| Очередь задач | `orchestrator/core/queue/` |
| Воркеры | `orchestrator/core/worker.py`, `worker_pool.py` |
| Планировщик | `orchestrator/core/scheduler.py` |
| Runner | `soar/runner.py` — точка входа для subprocess |
| Auth endpoints | `orchestrator/auth/router.py` — /auth/login, /auth/refresh, /auth/logout, /auth/me, /auth/keys |
| Auth dependencies | `orchestrator/auth/dependencies.py` — get_current_user, require_role |
| Auth models (ORM) | `orchestrator/auth/models.py` — User, RefreshToken, ApiKey |
| Auth service | `orchestrator/auth/service.py` — JWT, bcrypt, CRUD |
| DB session | `orchestrator/db/session.py` — init_engine, init_db, get_session_factory |
| Table prefix | `orchestrator/db/base.py` — configure_table_prefix, prefixed, fk |
| Job store (persistence) | `orchestrator/store/base.py` (интерфейс), `store/job_store.py` (memory), `store/sql_job_store.py` (SQL) |
| Alembic-миграции | `alembic/versions/` — `alembic upgrade head` / `alembic revision --autogenerate -m "..."` |
| Создать пользователя | `python -m orchestrator.auth.cli create-user --username X --role admin` |
| Конфиг | `orchestrator/config.py`, `orchestrator/config.yaml` |
| UI | `ui/src/views/` — Status, Workflows, Jobs, Actions, Connectors |
| Deploy | `deploy/stage/` — docker-compose.yml, Dockerfiles |
| Тесты | `tests/orchestrator/`, `tests/soar/` |

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
  параметрами конструктора?". Примеры: `OpenAPIGenerator` (генератор
  коннектора из спеки — работает с любым OpenAPI), `WatermarkStore`/
  `SeenStore` (durable курсор/TTL-дедуп — общий примитив для любого
  polling/webhook-приёмника), `CachedHttpClient` (v0.6, план — TTL-кэш
  HTTP per-domain для threat-intel actions)
  `actions/` — всё простое и специфичное для одной интеграции: бизнес-
  правила, decision-логика, магические значения (endpoint-пути, теги,
  имена workflow) — даже если внутри action используется класс из
  `tools/`. Пример: диспетчеризация события во внешнюю систему (кому
  какой workflow триггерить, при каких условиях) — решение specific для
  одной интеграции, не переиспользуется. Если модуль смешивает
  универсальную механику с интеграционными дефолтами (TTL-кэш с
  fallback — универсален, форма конкретной policy и её endpoint — нет)
  — механику оставить в `tools/`, специфику вынести в `actions/`
- **Каждый класс в `soar/tools/` обязан быть документирован и обнаружим
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

## Version history

- **v0.1** (2026-06-30) — Minimal SOAR: connectors, actions, workflows, orchestrator, UI, Docker deploy
- **v0.2** (2026-07-01) — Enterprise SOAR connectors: SSH, AD, FreeIPA, Elastic, SecurityOnion, Wazuh, PostgreSQL/MySQL/MSSQL, Telegram, SMTP, VirusTotal, Abuse.ch, File
- **v0.3** (2026-07-02) — Security hardening: 11 critical + 12 important fixes. SSRF protection, Zip Slip prevention, SQL/LDAP injection fixes, path traversal guards, rate limiting, subprocess lifecycle management
- **v0.4** (2026-07-02) — BIG FIX: DELETE workflow state cleanup, webhook token in API responses, additional connector hardening. Rate limiting (120 req/60s), SSRF protection for OpenAPI preview, SSH WarningPolicy, WinRM SSL verification, Wazuh secure defaults, MySQL identifier validation, SMTP attachment existence check, subprocess config path resolution, workflow registry filename-based keys, Redis queue triggered_at serialization, worker cancel skip + finally cleanup, CORSMiddleware credentials=False
- **v0.5** (2026-07-03) — Reliability + Bug fixes. ConcurrencyPolicy.QUEUE в Worker (busy-wait), `concurrency` в WorkflowJob и enqueue, `JobStore.recover_on_startup()`. Bug fixes (7): B1 cancel race, B2 MySQL backtick, B3 RedisQueue concurrency serialization, B4 result_data from log, B5 trusted_proxies rate limiter, B6 SSRF DNS resolve, B7 public API for private fields
- **v0.5.1** (2026-07-06, feature/auth) — Authentication: JWT (HS256, access 30min + refresh 7d, rotation), API keys (M2M, `soar_<hex>`), RBAC (admin/analyst/viewer/service), bcrypt пароли, SQLAlchemy 2.0 async DB layer, CORS с credentials, login rate limiter (5/60s), backward-compat auth-disabled mode. 21 тест, 341/342 passed.
- **v0.5.2** (2026-07-09) — IRP-интеграция (SOC Core Control): IRPConnector (`soar/connectors/irp/`) + четыре workflow поверх контракта `docs/integration/soc-core-integration-contract.md` — `alert_triage` (pull ES → триаж → ingest, чанк-реплей догона), `irp-events` (webhook-приёмник событий IRP), `irp_reconcile` (поллер-страховка), `respond_basic` (первый response-плейбук, без деструктива). Durable watermark/дедуп (`soar/tools/watermark.py`), кэш политик триажа из SOC Core settings API (`soar/tools/triage_policy.py`). Конфиг — секция `irp:` в `config.yaml`, `enabled: false` по умолчанию (shadow-режим обязателен до cutover)
- **v0.5.3** (2026-07-10) — Откат IRP-интеграции (v0.5.2): удалён `IRPConnector`, четыре workflow (`alert_triage`, `irp-events`, `irp_reconcile`, `respond_basic`), `soar/tools/{irp_settings,irp_dispatch,triage_policy}.py`, секция `irp:` в обоих `config.yaml`. Причина: бизнес-логика и настройки интеграции обходили API-редактируемые поверхности (см. "Архитектурный принцип: движок vs поведение"); решено не чинить точечно, а строить следующую интеграцию через API (см. v0.6). Контракт (`docs/integration/soc-core-integration-contract.md`) сохранён как референс. Добавлен read-only `GET /tools`/`GET /tools/{name}` (AST-интроспекция `soar/tools/`, без импорта модулей) — обнаружимость оставшихся generic-примитивов (`OpenAPIGenerator`, `WatermarkStore`/`SeenStore`) для того, кто будет строить интеграции дальше
- **v0.6** (planned) — Tooling: `CachedHttpClient` в `soar/tools/` (InMemory/Redis, TTL per-domain, request logging) для threat-intel actions; расширение `/status` in-memory метриками per-workflow (FP-rate, MTTR)
- **v0.7** (2026-07-17) — PostgreSQL migration с обратной совместимостью SQLite. Общий `database:` конфиг (`url`, `table_prefix`) теперь используется и auth-таблицами, и (опционально) job-историей — единая точка переключения бэкенда, без дублирования настроек. `table_prefix` — префикс имён таблиц для конфликтов при совместном использовании БД (`configure_table_prefix()`/`prefixed()`/`fk()` в `orchestrator/db/base.py`, применяется до импорта ORM-моделей). `AbstractJobStore` (`orchestrator/store/base.py`) — интерфейс, `InMemoryJobStore` (бывший `JobStore`, дефолт) и новый `SQLJobStore` (persistent, `jobs.persistence: sql`) — закрывает Known Limitations #3/#4 (crash recovery, история jobs переживает рестарт) при включении `sql`. Alembic-миграции (`alembic/`) — production-путь для будущих schema-изменений (`create_all()` остаётся для dev/test, только создаёт отсутствующие таблицы). `deploy/stage` — сервис `postgres`, пример конфига с Postgres + `table_prefix` + `jobs.persistence: sql`. Проверено end-to-end на реальном Docker Compose стенде: job сохраняется в Postgres с префиксом, переживает `docker compose restart` оркестратора.
