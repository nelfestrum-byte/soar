# SOAR

Минималистичный SOAR (Security Orchestration, Automation and Response) без
LLM: детерминированные автоматические расследования на ECS-схеме,
автоматическое закрытие стандартных кейсов с ложными срабатываниями.

Подробная архитектура, паттерны и правила разработки — в [AGENTS.md](AGENTS.md).
Этот README — про запуск, конфигурацию и деплой.

## Компоненты

| Компонент | Назначение |
|---|---|
| [`soar/`](soar/) | Python-пакет: коннекторы к внешним системам, actions, workflows |
| [`orchestrator/`](orchestrator/) | FastAPI-сервис: очередь задач, воркеры, планировщик, git-версионирование конфигурации |
| [`ui/`](ui/) | Vue.js SPA — стенд для ручного тестирования, не часть продукта |

## Быстрый старт (локально)

```bash
python -m pip install -r orchestrator/requirements.txt
python -m uvicorn orchestrator.main:app --reload --port 8000
```

Без `config.yaml` в рабочей директории сервис стартует с дефолтами:
SQLite-файл `./soar.db`, in-memory очередь и job-store, auth выключена
(анонимный admin — см. [Auth](#auth)). API — `http://localhost:8000/status`,
Swagger — `http://localhost:8000/docs`.

Тесты, линт, типы:

```bash
python -m pytest tests/ -v
ruff check .
mypy orchestrator/ soar/ --ignore-missing-imports
```

## Конфигурация (`config.yaml`)

Путь к файлу — переменная окружения `SOAR_CONFIG` (по умолчанию
`config.yaml` в рабочей директории). Все секции опциональны — отсутствующие
берут значения по умолчанию из `orchestrator/config.py`.

### `workers`

| Поле | По умолчанию | Описание |
|---|---|---|
| `count` | `4` | Число воркеров (asyncio tasks), исполняющих jobs параллельно |
| `default_timeout` | `300` | Таймаут выполнения workflow в секундах, если не задан в его meta |

### `queue` — очередь задач

| Поле | По умолчанию | Описание |
|---|---|---|
| `backend` | `memory` | `memory` (один инстанс) или `redis` (распределённое развёртывание) |
| `redis_url` | `redis://localhost:6379/0` | Только для `backend: redis` |
| `redis_max_connections` | `10` | Размер пула соединений |
| `redis_push_timeout` | `5.0` | Таймаут постановки job в очередь, сек |
| `redis_pop_timeout` | `1.0` | Таймаут ожидания job воркером, сек |

`memory` — только для одного инстанса оркестратора; `redis` — при
нескольких инстансах/распределённой нагрузке. См. Known Limitation #2 в
[AGENTS.md](AGENTS.md#known-limitations) (at-most-once delivery).

### `database` — SQLite / PostgreSQL

| Поле | По умолчанию | Описание |
|---|---|---|
| `url` | `sqlite+aiosqlite:///./soar.db` | SQLAlchemy async URL. Переключение SQLite↔PostgreSQL — только этим полем, отдельного флага backend нет |
| `pool_size` | `10` | Игнорируется для SQLite |
| `max_overflow` | `20` | Игнорируется для SQLite |
| `table_prefix` | `""` | Префикс имён таблиц (`^[a-zA-Z0-9_]*$`) — см. ниже |

Используется auth-таблицами (`users`, `refresh_tokens`, `api_keys`) всегда,
и job-историей (`workflow_jobs`) — если `jobs.persistence: sql`.

**PostgreSQL:**

```yaml
database:
  url: postgresql+asyncpg://soar:soar@postgres:5432/soar
```

**table_prefix** — если одна физическая база данных используется
несколькими инстансами SOAR (staging + prod на одном Postgres, несколько
клиентских деплоев и т.п.), у каждого инстанса должен быть свой
`table_prefix`, иначе таблицы (`users`, `workflow_jobs`, ...) столкнутся по
имени:

```yaml
database:
  table_prefix: "stage_"
```

Применяется на уровне процесса при старте (до импорта ORM-моделей) —
не может быть изменён без рестарта. Подробности реализации —
[AGENTS.md → Database backend](AGENTS.md#database-backend-sqlitepostgresql-и-table-prefix).

### `jobs` — история выполнения workflow

| Поле | По умолчанию | Описание |
|---|---|---|
| `log_dir` | `/var/log/soar/jobs` | Каталог логов job (один файл на job) |
| `keep_completed` | `1000` | Сколько завершённых jobs хранить (FIFO-эвикшн) — только для `persistence: memory` |
| `persistence` | `memory` | `memory` (по умолчанию, история теряется при рестарте) или `sql` (персистентно, поверх `database.url`) |

```yaml
jobs:
  persistence: sql
```

С `sql` job-история переживает рестарт контейнера/процесса, а
`recover_on_startup()` реально восстанавливает зависшие `RUNNING` jobs
после падения (без `sql` это no-op — hранилище на старте пустое).

### `soar` — расположение расширяемого кода

| Поле | По умолчанию | Описание |
|---|---|---|
| `workflows_dir` | `/app/data/workflows` | `.py`-файлы workflow (имя файла = ключ в реестре) |
| `connectors_dir` | `/app/data/connectors` | Директории коннекторов (код + `.yml`-конфиг) |
| `actions_dir` | `/app/data/actions` | `.py`-файлы actions |
| `tools_dir` | `soar/tools` | Read-only discovery для `GET /tools` |

### `git` — версионирование конфигурации

| Поле | По умолчанию | Описание |
|---|---|---|
| `workflows_repo` | `/app/data` | Git-репозиторий, в который автокоммитится любое изменение через API |
| `author_name` / `author_email` | `SOAR Orchestrator` / `soar@local` | Автор автокоммитов |

### `logging`

| Поле | По умолчанию | Описание |
|---|---|---|
| `level` | `INFO` | Уровень логирования (loguru) |
| `file` | `/var/log/soar/orchestrator.log` | Файл лога сервиса |

### `server`

| Поле | По умолчанию | Описание |
|---|---|---|
| `trusted_proxies` | `[]` | IP реверс-прокси для корректного rate-limiting по реальному IP (`["127.0.0.1"]` за nginx в одном контейнере) |

### `auth` — JWT / API-key аутентификация {#auth}

| Поле | По умолчанию | Описание |
|---|---|---|
| `secret_key` | `""` | Пусто = **auth выключена**, все запросы — анонимный admin (Docker-сетевое доверие) |
| `access_token_ttl` | `1800` | TTL access-токена, сек |
| `refresh_token_ttl` | `604800` | TTL refresh-токена, сек |
| `algorithm` | `HS256` | Алгоритм JWT |
| `cors_origins` | `["http://localhost:3000", "http://localhost:5173"]` | Разрешённые origins (обязательны при `allow_credentials=True`, `"*"` не подходит) |

Создание пользователя:

```bash
python -m orchestrator.auth.cli create-user --username admin --role admin
```

Роли: `admin`, `analyst`, `viewer`, `service`. Подробности — [AGENTS.md → Authentication](AGENTS.md#authentication-orchestratorauth).

## Способы деплоя

### 1. Локально / dev (SQLite, in-memory очередь и job-store)

```bash
python -m uvicorn orchestrator.main:app --reload --port 8000
```

Ничего дополнительно поднимать не нужно — используется дефолтный
`config.yaml` из рабочей директории (или его отсутствие → дефолты).

### 2. Docker Compose — стенд (`deploy/stage/`)

Полный стек: orchestrator + UI + Redis (очередь) + PostgreSQL
(auth + job-история).

```bash
cd deploy/stage
docker compose up --build -d
```

Первый деплой на свежую БД — токены/таблицы уже создаёт сам сервис
(`create_all()` при старте), Alembic нужно только **пометить** как
смигрированный (не накатывать миграцию заново):

```bash
make migrate-stamp-initial
```

При будущих изменениях схемы (новая Alembic-миграция в составе релиза):

```bash
make migrate
```

- UI: `http://localhost:3000`
- API: `http://localhost:8000/status`, `http://localhost:8000/docs`

Конфиг стенда — [`deploy/stage/config.yaml`](deploy/stage/config.yaml)
(Postgres, `table_prefix: "stage_"`, `jobs.persistence: sql`, Redis-очередь).
Остальные команды (`up`/`down`/`logs`/`restart`/`status`) — [`deploy/stage/Makefile`](deploy/stage/Makefile),
подробнее — [`deploy/stage/README.md`](deploy/stage/README.md).

### 3. Production вне Docker Compose

Тот же образ/код, свой `config.yaml` с реальными `database.url` (managed
Postgres), `queue.backend: redis` (managed Redis), `auth.secret_key`
(сгенерированный секрет) и, при необходимости, `database.table_prefix`
(если БД шарится с другими окружениями/инстансами). Перед первым стартом на
уже существующей БД — та же логика stamp/upgrade, что и для Compose (см.
выше и [AGENTS.md → Database backend](AGENTS.md#database-backend-sqlitepostgresql-и-table-prefix)).

## Дальше

- [AGENTS.md](AGENTS.md) — архитектура, паттерны, security, known limitations, версии
- [`docs/compose/specs/`](docs/compose/specs/) — дизайн-документы фич
- [`docs/compose/plans/`](docs/compose/plans/) — пошаговые планы реализации
- [`docs/compose/reports/`](docs/compose/reports/) — отчёты о выполненных фичах
