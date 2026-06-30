# AGENTS.md — SOAR Project v0.1

## What is this

SOAR (Security Orchestration, Automation and Response) — система автоматизации инцидентов. Три компонента:

1. **`soar/`** — Python-пакет: коннекторы (Elastic, VirusTotal, Telegram, SMTP, File), actions, workflows, реестры
2. **`orchestrator/`** — FastAPI сервис: очередь задач, воркеры, планировщик, git-версионирование
3. **`ui/`** — Vue.js SPA: минималистичный UI для тестирования и QA

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
    ├── workflows.py           # GET/POST enable/disable, reload
    ├── workflow_files.py      # CRUD workflow файлов + templates
    ├── files.py               # CRUD файлов + git history
    ├── actions.py             # CRUD actions + templates
    ├── connectors.py          # CRUD connectors + code/config
    ├── jobs.py                # POST запуск, GET статус, cancel
    ├── webhooks.py            # POST webhook с токеном
    ├── logs.py                # GET лог + SSE стрим
    └── status.py              # GET /status — воркеры, очередь, статистика

soar/
├── __init__.py                # Экспорт connectors, actions, workflows
├── logger.py                  # setup_logging(), get_logger()
├── runner.py                  # Точка входа для subprocess workflows
├── connectors/
│   ├── __init__.py            # ConnectorRegistry — автообнаружение коннекторов
│   ├── base.py                # BaseConnector (lazy connect)
│   ├── elastic/               # ElasticConnector — query/index/delete
│   ├── virus_total/           # VirusTotalConnector — lookup IP/domain/file
│   ├── telegram/              # TelegramConnector — send messages/photos, get updates
│   ├── smtp/                  # SmtpConnector — send email (plain/HTML, attachments)
│   └── file/                  # FileConnector — write/read/append/delete файлы
├── actions/
│   ├── __init__.py            # ActionsRegistry — автообнаружение actions
│   ├── send_tg_soc_team.py    # Пример action
│   └── send_tg_message.py     # Отправка в Telegram канал
├── workflows/
│   ├── __init__.py            # WorkflowRegistry — автообнаружение workflows
│   ├── base.py                # BaseWorkflow, ScheduledWorkflow, WebhookWorkflow, ManualWorkflow
│   ├── alert_check.py         # Scheduled workflow (пример)
│   ├── webhook_to_file.py     # Webhook → запись в файл
│   ├── webhook_alert.py       # Webhook → Telegram с задержкой
│   └── send_tg_message.py     # Manual → Telegram
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
├── docker-compose.yml         # orchestrator + UI (nginx)
├── Dockerfile.orchestrator    # Python 3.11 + git + deps
├── Dockerfile.ui              # Node build → nginx
├── nginx.conf                 # proxy /api → orchestrator:8000
├── config.yaml                # Stage defaults
├── Makefile                   # make up/down/build/logs
└── README.md
```

## API Endpoints

### Workflows
| Method | Path | Description |
|--------|------|-------------|
| GET | /workflows | Список registered workflows |
| POST | /workflows/reload | Перечитать файлы и обновить job_manager |
| POST | /workflows/{name}/enable | Включить workflow |
| POST | /workflows/{name}/disable | Выключить workflow |

### Workflow Files
| Method | Path | Description |
|--------|------|-------------|
| GET | /workflow-files | Список файлов workflows |
| GET | /workflow-files/template | Шаблон (name, wf_type) |
| GET | /workflow-files/{name} | Получить код |
| PUT | /workflow-files/{name} | Сохранить код |
| DELETE | /workflow-files/{name} | Удалить файл |

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

## File map (для быстрого навигации)

| Что нужно | Куда смотреть |
|-----------|---------------|
| Добавить API эндпоинт | `orchestrator/api/*.py` |
| Новый коннектор | `soar/connectors/`, скопировать `elastic/` как шаблон |
| Telegram коннектор | `soar/connectors/telegram/` — send_message, send_photo, send_document, get_updates |
| SMTP коннектор | `soar/connectors/smtp/` — send_email, send_text, send_html (plain/HTML, CC/BCC, вложения) |
| File коннектор | `soar/connectors/file/` — write, write_json, append, read, list_files, delete |
| Новый action | `soar/actions/`, один файл = одна функция |
| Новый workflow | `soar/workflows/`, наследовать от `ScheduledWorkflow`/`WebhookWorkflow`/`ManualWorkflow` |
| Шаблон workflow | `orchestrator/api/workflow_files.py` — TEMPLATES dict |
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
