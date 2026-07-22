# Config Reference: Queue & Database Backend

Детали конфигурации очереди и БД. Индекс/навигация — в [AGENTS.md](../../AGENTS.md).
Критичная operational-готча (create_all vs alembic) вынесена коротко в основной файл — здесь полное объяснение.

## Queue backend

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

## Database backend (SQLite/PostgreSQL) и table prefix

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

### create_all() vs Alembic — полное объяснение готчи

**Alembic** — единственный источник схемы для новых изменений в продакшне.
`init_db()` (`create_all()`) по-прежнему выполняется на каждом старте
сервиса — но он только создаёт отсутствующие таблицы, никогда не меняет уже
существующие (не добавит новую колонку и т.п.), так что реальные будущие
миграции идут исключительно через Alembic:

```bash
alembic revision --autogenerate -m "<message>"     # сгенерировать новую миграцию
alembic upgrade head                               # применить миграции
```

**Важно (проверено на реальном Postgres в deploy/stage дважды — на первом
деплое и повторно при добавлении `audit_log` в v0.8):** это не
одноразовая проблема только первого деплоя, а общее правило для **любой**
миграции, которая только добавляет новую таблицу (не меняет существующую).
`create_all()` выполняется на каждом старте контейнера и создаёт
отсутствующие таблицы раньше, чем оператор успевает вызвать Alembic —
`alembic upgrade head` в этом случае упадёт с `DuplicateTableError`, т.к.
пытается создать уже существующие таблицы. Правильная последовательность
после деплоя образа с новой миграцией **только для новых таблиц**:
`docker compose up --build -d` (создаёт таблицу через `create_all()`) →
`alembic stamp head` (помечает БД как смигрированную без повторного
выполнения DDL), не `upgrade head`. `upgrade head` реально нужен только
когда миграция меняет существующую таблицу (добавление колонки и т.п.) —
тогда `create_all()` не поможет и `upgrade head` — единственный путь. См.
`deploy/stage/Makefile` (`make migrate-stamp-initial` / `make migrate`) —
несмотря на название, `migrate-stamp-initial` в реальности нужно
перепроверять при каждой новой чисто-новой-таблице миграции, не только на
первом деплое.

`SOAR_CONFIG` (тот же env var, что и у сервиса) определяет, какой
`config.yaml` читает `alembic/env.py` — миграции никогда не расходятся с
конфигом запущенного сервиса.
