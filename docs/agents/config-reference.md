# Config Reference: Queue & Database Backend

Детали конфигурации очереди и БД. Индекс/навигация — в [AGENTS.md](../../AGENTS.md).
Критичная operational-готча (create_all vs alembic) вынесена коротко в основной файл — здесь полное объяснение.

## Queue backend

Очередь задач поддерживает три бэкенда:

**In-Memory (дефолт схемы, не деплоя)**:
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
- At-most-once — может терять джобы при обрыве соединения (Known Limitations #2)

**SQL (дефолт `deploy/prod`/`deploy/stage` с v0.12)**:
```yaml
queue:
  backend: sql
  sql_poll_interval: 0.5   # секунд между claim-попытками при пустой очереди

jobs:
  persistence: sql   # обязателен вместе с backend: sql, иначе ValueError при старте
```

`SQLQueue` (`orchestrator/core/queue/sql_queue.py`) — не отдельный источник
правды, а poll поверх уже существующей таблицы `workflow_jobs`, которую
`JobManager.enqueue()` пишет durably до вызова `queue.push()`: `push()` —
no-op, `pop()` — атомарный claim (`UPDATE ... WHERE id = (SELECT ... FOR
UPDATE SKIP LOCKED)` на Postgres; на SQLite — тот же запрос без `SKIP
LOCKED`, полагается на файловую сериализацию записи одним writer'ом).
Устраняет at-most-once потерю джобов RedisQueue (Known Limitations #2) без
нового компонента в деплое. Partial-индекс `(status, triggered_at) WHERE
status='PENDING'` (`alembic/versions/42fbd47b0d46_*.py`) держит claim-запрос
дешёвым независимо от объёма исторических завершённых записей. Валиден
только вместе с `jobs.persistence: sql` — `create_queue()`
(`orchestrator/main.py`) fail-fast при рассинхроне.

**Job history retention (`jobs.retention_days`)** — только при
`jobs.persistence: sql`:
```yaml
jobs:
  retention_days: 90   # 0 (дефолт) = хранить бесконечно, явный опт-ин на удаление
```
`SQLJobStore.purge_old()` удаляет завершённые (COMPLETED/FAILED/TIMEOUT/
CANCELLED) записи старше порога; вызывается раз в 24ч через уже
существующий `OrchestratorScheduler`, только если `retention_days > 0`.
`InMemoryJobStore.purge_old()` — no-op (`keep_completed` уже делает
эквивалентную по смыслу эвикцию).

Спек/отчёт: `docs/compose/specs/2026-07-27-sql-job-queue-design.md`,
`docs/compose/reports/sql-job-queue.md`.

## Job-runner privilege narrowing (`jobs.runner_uid` и credential scoping)

Фаза 4 модели сущностей (`docs/concepts/ENTITY-MODEL.md`, слой 3
изоляции). Два независимых механизма — второй не требует первого:

**Credential scoping — всегда включён, без опции.** Каждый job-субпроцесс
получает не полный `orchestrator/config.yaml` (JWT-секрет,
`database.url`), а временный YAML-срез: `orchestrator/core/introspect.py
::parse_connector_usage` статически (AST, без импорта) находит `from
soar.connectors.<type> import <instance>` на верхнем уровне файла
воркфлоу, `orchestrator/core/subprocess_runner.py::build_scoped_config`
строит по этому списку временный `connectors_dir` (символические ссылки на
нужные `.py`, отфильтрованные `.yml` только с нужными инстансами).
Воркфлоу без статически найденных импортов (старый `connectors.<name>`
registry-путь, ошибка парсинга, отсутствующий файл) получают **пустой**
`connectors_dir`, не полный набор — см. `build_scoped_config`'s docstring
для обоснования (в репозитории нет примеров старой формы после Фазы 2).
Временный каталог (`job.scoped_config_dir`) удаляется в `Worker._execute`'s
`finally`, на всех путях выхода (успех/ошибка/timeout/cancel).

**UID/rlimit narrowing — опционален, POSIX/Docker-only, `None` по
умолчанию (без изменений в поведении):**
```yaml
jobs:
  runner_uid: 5001        # None (дефолт) = не понижать привилегии
  runner_gid: 5001         # None = использовать runner_uid как gid
  runner_max_memory_mb: 512
  runner_max_cpu_seconds: 300
  runner_max_procs: 32
```
Требует образ, собранный из `deploy/{prod,stage}/Dockerfile.orchestrator`
этой версии — отдельный пользователь `soar-runner` (фиксированный
uid/gid `5001`), `setpriv` с файловой capability
`cap_setuid,cap_setgid+ep`, `config.yaml` mode `640` (`soar:soar`),
`/app/data/state` group-writable `soar-runner`. Механизм — не прямой
`os.setuid`/`os.setgid` в `preexec_fn` (не работает без CAP_SETUID у
самого интерпретатора — см. `docs/compose/reports/privilege-narrowing.md`
для замеров в Docker), а обёртка argv в `setpriv --reuid=... --regid=...`;
rlimits (`RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_NPROC`) по-прежнему через
`preexec_fn`, они не требуют capability. Полное описание, включая
компромисс по механизму — `docs/agents/security-patterns.md` и отчёт фазы.

## HTTP client (soar/tools/http_client.py)

Общий инструмент для threat-intel actions (VT, AbuseCh, Shodan, Fofa, Censys,
MISP, RstCloud, Kaspersky, URLhaus, crt.sh) — логирование каждого запроса
безусловно (loguru, method/domain/status/duration_ms/cache_hit), кэш GET-ответов
опционален:

```yaml
http_client:
  cache_backend: memory   # memory | redis | none
  default_ttl: 3600
  domain_ttl:
    api.virustotal.com: 86400
```

`cache_backend: redis` переиспользует `queue.redis_url` — отдельного поля
нет; пустой `queue.redis_url` с `cache_backend: redis` — ошибка конфигурации
при старте, не тихий fallback на memory. `POST` никогда не кэшируется.
Singleton `soar.tools.http_client`, инициализируется в `soar/runner.py` из
того же `SOAR_CONFIG`, что и остальной конфиг subprocess-раннера. Пока не
используется существующими коннекторами — миграция на этот клиент
отдельная задача (см. `docs/compose/specs/2026-07-27-http-client-design.md`
[S9]).

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
