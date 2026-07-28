# AGENTS.md — SOAR Project v0.13

> Это индекс. Детали вынесены в сателлитные файлы под `docs/agents/` и в `CHANGELOG.md` —
> открывай их только когда задача реально их касается (см. Token optimization внизу).

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

# Stage deploy (Docker) — internal QA, build: from source
cd deploy/stage && docker compose up --build

# Prod deploy (Docker, distributable) — build machine, then transfer bundle
python deploy/soarctl package --version X.Y.Z --output soar-bundle-X.Y.Z.tar.gz
# target machine (offline from here on)
python soarctl install soar-bundle-X.Y.Z.tar.gz --dir soar-prod && cd soar-prod
python soarctl init && python soarctl up && python soarctl migrate --fresh
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
│   ├── worker.py              # Worker — один воркер, цикл pop → execute
│   ├── worker_pool.py         # WorkerPool — N воркеров как asyncio tasks
│   ├── scheduler.py           # OrchestratorScheduler (APScheduler) — + периодическая retention_cleanup job (jobs.retention_days > 0)
│   ├── job_manager.py         # JobManager — координатор, enqueue/cancel
│   ├── subprocess_runner.py   # Запуск workflows как subprocess
│   ├── git_manager.py         # Git операции через subprocess (commit принимает author_name/author_email override; nothing-to-commit определяется через `git diff --cached --quiet`, не string-match stderr)
│   ├── history.py             # Тонкие обёртки над GitManager для history/diff/restore (общие для workflows/actions/connectors)
│   ├── workflow_state.py      # Единственный читатель/писатель orchestrator_state.yaml (enable/disable + webhook token)
│   ├── introspect.py          # parse_classes/parse_functions — AST-интроспекция без импорта, общая для tools.py/actions.py/connectors.py; parse_classes также извлекает fields (тип+дефолт) и hidden_fields (HIDDEN_FIELDS) для connector schema
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
    ├── actions.py               # CRUD actions + templates + history/diff/restore + GET {name}/describe
    ├── connectors.py            # CRUD connectors + code/config + OpenAPI generate/preview + history/diff/restore + GET {name}/describe
    ├── jobs.py                  # POST запуск, GET статус, cancel
    ├── webhooks.py              # POST webhook с токеном
    ├── logs.py                  # GET лог + SSE стрим
    ├── status.py                # GET /status, GET /health
    ├── transfer.py               # POST export/import — импорт/экспорт конфигурации
    ├── tools.py                  # GET /tools — read-only discovery (AST, без импорта) для soar/tools/
    ├── prompts.py                 # GET /prompts/system (read-only, versioned с кодом) + GET/PUT /prompts/user (admin, git-CRUD)
    ├── audit.py                  # GET /audit-log — admin-only, paginated, фильтры
    └── validation.py              # validate_name, validate_path_within, SSRF validation

soar/
├── connectors/                 # 24 коннектора (23 интеграции + file), автообнаружение через ConnectorRegistry — полный список см. File map; каждый объявляет class-level HIDDEN_FIELDS для редакции секретов в config API
├── actions/__init__.py         # ActionsRegistry — автообнаружение actions
├── workflows/                  # __init__.py (WorkflowRegistry), base.py (BaseWorkflow/ScheduledWorkflow/WebhookWorkflow/ManualWorkflow)
├── tools/                      # openapi.py (OpenAPIGenerator), watermark.py (WatermarkStore/SeenStore), http_client.py (HttpClient singleton — логирование безусловно, кэш опционален) — см. File map
├── runner.py                   # Точка входа для subprocess workflows — см. Runner contract; также инициализирует soar.tools.http_client singleton из SOAR_CONFIG
└── examples/nadproject_integration.py

ui/src/                         # Vue 3 SPA, полный список views — см. File map
alembic/                        # Alembic-миграции (auth + workflow_jobs + audit_log таблицы), см. docs/agents/config-reference.md
deploy/stage/                   # QA docker-compose (build: from source) + Makefile
deploy/prod/                    # Distributable profile — image: не build:, config.yaml не в git, см. deploy/prod/README.md
deploy/soarctl, soarctl_lib/    # Host-layer CLI: package/install/init/up/update/migrate/users/backup/doctor
                                 # git_source.py — on-site install (--repo) + update, no bundle/air-gap

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
Исключение: `POST /transfer/{export,import}` пока не пишет audit-запись (см.
`docs/concepts/BAGFIX_PLAN.md` S3). `POST /jobs` и `POST /webhooks/{name}`
пишут `job.create` — у вебхука нет `CurrentUser` (нет JWT/RBAC на этом роуте),
поэтому актор синтетический: `CurrentUser(id=0, role="service", type="webhook",
username=f"webhook:{workflow_name}")`, третье значение `actor_type` (кроме
`"user"`/`"service"`).

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
все HTTP-коннекторы — `timeout=30`.

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
| HTTP client (логирование + опциональный кэш) | `soar/tools/http_client.py` — HttpClient singleton, `http_client:` секция конфига, см. `docs/agents/config-reference.md` |
| Connector config schema / секреты | `orchestrator/core/introspect.py` (`_fields`/`_hidden_fields`), `orchestrator/api/connectors.py` (`GET /schema`, редакция config/history/diff), `HIDDEN_FIELDS` на каждом коннекторе |
| Новый action | `soar/actions/`, один файл = одна функция |
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
| UI | `ui/src/views/` — Status, Workflows, Jobs, Actions, Connectors, AuditLog, ApiKeys, Users, Tools, Generate, Settings, Login, Logs |
| Deploy (QA-стенд) | `deploy/stage/` — docker-compose.yml (build:), Dockerfiles |
| Deploy (дистрибуция, air-gap) | `deploy/prod/` (docker-compose.yml с `image:`, config.yaml.template) + `deploy/soarctl`/`soarctl_lib/` — package/install/init/up/migrate/users/backup/doctor, см. `docs/compose/specs/2026-07-22-deploy-cli-design.md` |
| Deploy (дистрибуция, on-site/с интернетом) | `soarctl install --repo <url-or-path> [--ref REF]` — сборка образов на месте, без bundle; `soarctl init --interactive`/`--cors-origin` — заполняет `auth.cors_origins` вместо плейсхолдера; `soarctl update [--ref REF] [--migrate fresh\|upgrade]` — git pull/checkout + пересборка + `up`, без `down`, postgres/redis не пересоздаются; `soarctl_lib/git_source.py`, `prompts.py`; см. `docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md` |
| Тесты | `tests/orchestrator/`, `tests/soar/`, `tests/deploy/` |
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
  параметрами конструктора?". Примеры: `OpenAPIGenerator` (генератор
  коннектора из спеки — работает с любым OpenAPI), `WatermarkStore`/
  `SeenStore` (durable курсор/TTL-дедуп — общий примитив для любого
  polling/webhook-приёмника), `HttpClient` (v0.12 — логирование безусловно +
  TTL-кэш per-domain опционален, для threat-intel actions)
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
8. **Сателлиты по требованию** — `docs/agents/*.md` и `CHANGELOG.md` открывай только когда задача
   реально касается API-контрактов, security-механизмов, known limitations или истории версий —
   не читай их "на всякий случай" при каждой сессии

## Version history

Полная история версий — **[CHANGELOG.md](CHANGELOG.md)**.

Текущая версия: **v0.13** (2026-07-27) — `soarctl` on-site install + update:
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

Предыдущая версия: **v0.11** (2026-07-22) — Agent Dev-Loop Этап 1: validation перед записью
кода (workflows/actions/connectors), traceback в WorkflowResult, history/diff/restore
(`orchestrator/core/history.py`), единый `orchestrator/core/workflow_state.py` для
`orchestrator_state.yaml`.
