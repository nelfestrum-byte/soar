# AGENTS.md — SOAR Project v0.4

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
│   └── job_store.py           # JobStore — in-memory хранение jobs
└── api/
    ├── workflows.py           # GET/POST enable/disable, reload + CRUD кода workflow
    ├── actions.py             # CRUD actions + templates
    ├── connectors.py          # CRUD connectors + code/config + OpenAPI generate/preview
    ├── jobs.py                # POST запуск, GET статус, cancel
    ├── webhooks.py            # POST webhook с токеном
    ├── logs.py                # GET лог + SSE стрим
    ├── status.py              # GET /status — воркеры, очередь, статистика
    ├── transfer.py            # POST export/import — импорт/экспорт конфигурации
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
│   └── openapi.py             # OpenAPI connector code generator
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

deploy/stage/
├── docker-compose.yml         # orchestrator :8000 (direct API) + UI :3000 (nginx proxy)
├── Dockerfile.orchestrator    # Python 3.11 + git + deps
├── Dockerfile.ui              # Node build → nginx
├── nginx.conf                 # proxy /api, /docs, /openapi.json → orchestrator:8000
├── config.yaml                # Stage defaults
├── Makefile                   # make up/down/build/logs
└── README.md
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
| PUT | /actions/{name} | Сохранить код |
| DELETE | /actions/{name} | Удалить action |

### Connectors
| Method | Path | Description |
|--------|------|-------------|
| GET | /connectors | Список коннекторов |
| POST | /connectors/{name} | Создать коннектор |
| DELETE | /connectors/{name} | Удалить коннектор |
| GET | /connectors/{name}/code | Получить код .py |
| PUT | /connectors/{name}/code | Сохранить код .py |
| GET | /connectors/{name}/config | Получить конфиг .yml |
| PUT | /connectors/{name}/config | Сохранить конфиг .yml |
| POST | /connectors/generate | Генерация коннектора из OpenAPI spec |
| POST | /connectors/preview | Парсинг OpenAPI spec (POST, тело) |
| GET | /connectors/preview | Парсинг OpenAPI spec (GET, URL) — SSRF-защищён |

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

## Security patterns

### Input validation (orchestrator/api/validation.py)
- `validate_name(name)` — regex `^[a-zA-Z0-9_\-]+$`, блокирует path traversal и shell metacharacters
- `validate_path_within(base, target)` — `normpath + startswith`, предотвращает directory escape
- SSRF protection — блокировка RFC 1918, link-local, localhost, cloud metadata IPs

### Connector security (soar/connectors/)
- SQL: параметризованные запросы (PostgreSQL, MSSQL) + валидация имён (MySQL)
- LDAP: RFC 4515 escaping спецсимволов (`*`, `(`, `)`, `\`, NUL)
- File: path boundary check через `_resolve()` + `resolve()` + `startswith()`
- SSH: `WarningPolicy()` вместо `AutoAddPolicy()` (MITM protection)
- WinRM: SSL verification по умолчанию (`verify_ssl=True`)
- HTTP: `timeout=30` на все HTTP-запросы (prevents worker pool exhaustion)
- Wazuh: пустые credentials по умолчанию, SSL verification включён

### Rate limiting (orchestrator/main.py)
- In-memory rate limiter: 120 req/60s per IP
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
- `CORSMiddleware(allow_credentials=False)` — security best practice

## Known limitations

- **ConcurrencyPolicy.QUEUE** — не реализован, работает как ALLOW
- **RedisQueue** — brpop может терять сообщения при обрыве соединения; serialized data не полный (без `triggered_at`)
- **No authentication** — сервис доверяет Docker-сети
- **Worker crash recovery** — jobs в статусе RUNNING без активного процесса не восстанавливаются автоматически

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
| Новый action | `soar/actions/`, один файл = одна функция |
| Новый workflow | `soar/workflows/`, наследовать от `ScheduledWorkflow`/`WebhookWorkflow`/`ManualWorkflow` |
| Шаблон workflow | `orchestrator/api/workflows.py` — TEMPLATES dict |
| Изменить модель | `orchestrator/models/` |
| Очередь задач | `orchestrator/core/queue/` |
| Воркеры | `orchestrator/core/worker.py`, `worker_pool.py` |
| Планировщик | `orchestrator/core/scheduler.py` |
| Runner | `soar/runner.py` — точка входа для subprocess |
| Конфиг | `orchestrator/config.py`, `orchestrator/config.yaml` |
| UI | `ui/src/views/` — Status, Workflows, Jobs, Actions, Connectors |
| Deploy | `deploy/stage/` — docker-compose.yml, Dockerfiles |
| Тесты | `tests/orchestrator/`, `tests/soar/` |

## Rules

- НЕ коммитить `orchestrator_state.yaml` — только `config.yaml` и код
- НЕ хранить реальные `*.yml` коннекторов в git — только `*.example.yml`
- НЕ писать бизнес-логику в API роутах — только вызовы JobManager/GitManager
- НЕ обращаться к очереди напрямую из роутов — только через JobManager.enqueue()
- Все пути через config, без хардкода
- Авторизация не нужна — сервис доверяет локальной Docker-сети

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
