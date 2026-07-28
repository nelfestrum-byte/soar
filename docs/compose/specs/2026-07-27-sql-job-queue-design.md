# SQL-Backed Job Queue + Job History Retention

> Реализует P14 из `docs/concepts/UPGRADE-v2.md`. Заменяет `queue.backend:
> redis` по умолчанию для критичных workflows на poll-based очередь поверх
> той же таблицы `workflow_jobs`, которую уже пишет `SQLJobStore` при
> `jobs.persistence: sql` — устраняет at-most-once потерю джобов
> (known-limitation #2) без новой инфраструктуры и без замены
> `JobManager`/`Worker`/`ConcurrencyPolicy`.

## [S1] Problem

`RedisQueue.pop()` (`orchestrator/core/queue/redis_queue.py:74-100`) читает
через `BRPOP` — атомарный на стороне Redis-сервера. Если TCP-соединение
рвётся **после** того, как Redis уже удалил элемент из списка `soar:jobs`,
но **до** того как ответ дошёл до воркера, джоб пропадает необратимо: его
нет ни в Redis (уже отдан), ни у клиента (сеть не донесла). At-most-once,
без ACK, без ретрая — комментарий в самом коде это признаёт (строки 74-76).

Это усугубляется тем, что `deploy/prod/docker-compose.yml`/`deploy/stage/
docker-compose.yml` поднимают `redis:7-alpine` без кастомного
`redis.conf`/`command` — персистентность только дефолтные RDB-снапшоты
(`save 3600 1 / 300 100 / 60 10000`), AOF выключен. При блэкауте/
перезагрузке VM теряется хвост между последним снапшотом и крашем — то
есть проблема не только "живой сетевой сбой", но и "плановый/аварийный
рестарт роняет часть очереди".

Важный факт, обнаруженный при разборе: `JobManager.enqueue()`
(`orchestrator/core/job_manager.py:94-96`) пишет запись в `JobStore` со
статусом `PENDING` **до** `queue.push()`. Если `jobs.persistence: sql`, эта
запись переживает рестарт — но `recover_on_startup()`
(`orchestrator/store/sql_job_store.py:130-145`) трогает только `RUNNING`
(переводит в `FAILED`), про `PENDING` ничего не знает. Значит потерянный в
очереди джоб оставляет орфанную `PENDING`-запись навсегда — сигнал есть,
но его никто не читает и не реенкьюит.

**Рассмотренные и отклонённые альтернативы** (из обсуждения):
- **Redis Streams + consumer group** (`XADD`/`XREADGROUP`/`XACK`/
  `XAUTOCLAIM`) — закрывает саму гонку, но не даёт ничего сверх варианта
  ниже и всё равно требует AOF-персистентности Redis отдельно для
  блэкаут-сценария.
- **Celery + Redis** — battle-tested ack/redelivery слой, но требует
  заменить `JobManager`/`Worker`/ручную реализацию `ConcurrencyPolicy`
  (`worker.py:47-54`, known-limitation #1) на модель Celery, плюс новый
  компонент в деплое (celery worker/beat, Flower). Непропорционально
  тяжело для масштаба этого проекта.
- **RabbitMQ** — не даёт надёжность бесплатно (нужны durable queue +
  manual ack + publisher confirms, настраивается не проще Redis AOF) и
  добавляет отдельный сервис в деплой без структурного преимущества перед
  вариантом ниже.
- **PGSQL-native retention** (`pg_cron`, партиционирование) — рассмотрено
  для другой части задачи (retention, см. [S6]) и отклонено: ломает
  портативность SQLite-бэкенда (`jobs.persistence: sql` = Postgres ИЛИ
  SQLite-файл, known-limitation #3/#4) и требует extension, отсутствующего
  в ванильном `postgres:16-alpine`.

## [S2] Solution Overview

1. Новый `SQLQueue(AbstractJobQueue)` — не отдельная таблица, а poll поверх
   уже существующей `workflow_jobs` (`orchestrator/store/models.py::
   JobRecord`). `push()` — no-op: запись уже сделана durably со статусом
   `PENDING` в `JobManager.enqueue()` до вызова `queue.push()`. `pop()` —
   атомарный claim-запрос (см. [S4]).
2. `queue.backend: sql` валиден только вместе с `jobs.persistence: sql` —
   проверка при старте (`lifespan()`, `orchestrator/main.py`), fail-fast
   при рассинхроне: `SQLQueue` без SQL-бэкенда `JobStore` не имеет смысла,
   это не отдельный источник правды, а тот же самый.
3. `_job_to_record`/`_record_to_job` (сейчас module-private в
   `sql_job_store.py:25-64`) выносятся в `orchestrator/store/mapping.py`,
   переиспользуются и `SQLJobStore`, и `SQLQueue` — без дублирования и без
   обращения к приватным функциям другого модуля.
4. Partial-индекс на `(status, triggered_at) WHERE status = 'PENDING'` —
   claim-запрос остаётся дешёвым независимо от объёма исторических
   COMPLETED/FAILED-записей (см. [S5], закрывает риск "деградация от роста
   таблицы" отдельно от retention).
5. `jobs.retention_days` — новый конфиг, периодическая очистка старых
   завершённых джобов через уже существующий `OrchestratorScheduler`
   (`orchestrator/core/scheduler.py`), без нового компонента в деплое.
6. Redis остаётся доступен как backend — но не дефолт для критичных
   workflows; известное применение по known-limitation #2 сужается до
   "high-throughput non-critical", если он вообще понадобится.

## [S3] Architecture

```
orchestrator/
├── core/
│   └── queue/
│       └── sql_queue.py           # NEW: SQLQueue(AbstractJobQueue)
├── store/
│   ├── mapping.py                 # NEW: _job_to_record/_record_to_job (moved out of sql_job_store.py)
│   ├── sql_job_store.py           # MODIFY: import mapping from mapping.py; + purge_old()
│   ├── base.py                    # MODIFY: + abstractmethod purge_old(retention_days) -> int
│   ├── job_store.py               # MODIFY: purge_old() no-op (keep_completed уже делает эквивалент)
│   └── models.py                  # MODIFY: doc-comment про новый partial index (см. миграцию)
├── config.py                      # MODIFY: QueueConfig.sql_poll_interval; JobsConfig.retention_days
├── core/scheduler.py               # MODIFY: + internal retention job (IntervalTrigger)
└── main.py                        # MODIFY: create_queue() — "sql" branch; fail-fast validation

alembic/versions/
└── <rev>_add_workflow_jobs_pending_index.py   # NEW: partial index (status, triggered_at)

deploy/
├── prod/config.yaml.template       # MODIFY: queue.backend: sql (было redis), + jobs.retention_days
└── stage/config.yaml               # MODIFY: то же, для консистентности со стендом

tests/orchestrator/
├── core/queue/test_sql_queue.py    # NEW
├── store/test_sql_job_store.py     # MODIFY: + purge_old() тесты
└── test_main_job_store_factory.py  # MODIFY: fail-fast тест (sql-queue без sql-persistence → ValueError)
```

## [S4] Atomic Claim Query

Postgres (использует `FOR UPDATE SKIP LOCKED`, доступно с 9.5):

```sql
UPDATE workflow_jobs
SET status = 'RUNNING', started_at = :now
WHERE id = (
    SELECT id FROM workflow_jobs
    WHERE status = 'PENDING'
    ORDER BY triggered_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

SQLite не поддерживает `FOR UPDATE SKIP LOCKED` — не нужен: SQLite
сериализует запись на уровне файла (один writer), тот же `UPDATE ... WHERE
id = (SELECT ...)` в одной транзакции даёт ту же гарантию "ровно один
воркер забирает джоб" без явной блокировки. Ветвление по диалекту —
`session.bind.dialect.name` в `SQLQueue.pop()`; точная формулировка (raw
SQL vs SQLAlchemy Core `update().where().returning()`, поддержка
`RETURNING` на SQLite 3.35+) — на этапе плана, с тестами на оба диалекта
(`test_sql_job_store.py` уже использует `sqlite+aiosqlite:///:memory:` для
CI — тот же фикстур-паттерн для `test_sql_queue.py`).

`SQLQueue.pop(timeout)` — нет блокирующего примитива как у `BRPOP`/
`asyncio.Queue.get`: цикл `try claim → если пусто, asyncio.sleep(poll_interval)`
до истечения `timeout`, сохраняя контракт `AbstractJobQueue.pop()`
(`orchestrator/core/queue/base.py:10-11`) идентичным для `Worker.run()`
(`worker.py:35`) — вызывающий код не меняется. `poll_interval` — новый
конфиг `queue.sql_poll_interval: float = 0.5`, не завязан на Postgres
`LISTEN/NOTIFY` (возможная будущая оптимизация задержки, вне скоупа: при
масштабе IR-джобов, не high-frequency потока, не требуется сейчас).

## [S5] Partial Index (миграция)

```python
def upgrade() -> None:
    op.create_index(
        "ix_workflow_jobs_pending_triggered_at",
        "workflow_jobs",
        ["status", "triggered_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
        sqlite_where=sa.text("status = 'PENDING'"),
    )

def downgrade() -> None:
    op.drop_index("ix_workflow_jobs_pending_triggered_at", table_name="workflow_jobs")
```

Литеральное имя таблицы `workflow_jobs`, не `prefixed("workflow_jobs")` —
существующие миграции (`alembic/versions/3067dea7c75b_*.py`) уже не
учитывают `table_prefix` (known-limitation #9), эта миграция следует тому
же прецеденту, не расширяет и не чинит его.

> **Обновление (BAGFIX_PLAN S6,
> `docs/compose/specs/2026-07-28-workflow-jobs-index-table-prefix-design.md`):**
> этот индекс, объявленный только здесь (в миграции), молча не создавался
> на штатной последовательности первой установки — `soarctl migrate
> --fresh` выполняет `alembic stamp head`, который не запускает DDL.
> Исправлено: `orchestrator/store/models.py::JobRecord.__table_args__`
> теперь тоже объявляет тот же индекс (`Index(...)`, то же имя через
> `prefixed()`), так что `create_all()` создаёт его на любой свежей
> инсталляции. Эта миграция остаётся нужной и корректной — она создаёт
> индекс при апгрейде уже существующей инсталляции, где `create_all()`
> таблицу не трогает. Заодно исправлен литерал `workflow_jobs` на
> `prefixed("workflow_jobs")` — индекс гарантированно создаётся на любом
> пути установки, не только апгрейд-пути.

## [S6] Retention: `jobs.retention_days`

`orchestrator/config.py::JobsConfig`:

```python
class JobsConfig(BaseModel):
    log_dir: str = "/var/log/soar/jobs"
    keep_completed: int = 1000
    persistence: str = "memory"  # memory | sql
    retention_days: int = 0  # 0 = disabled — explicit opt-in, не тихий дефолт
```

Дефолт `0` (выключено) на уровне схемы — удаление истории не должно быть
тихим поведением из коробки, тот же принцип, что и P14 про
`queue.backend`. В `deploy/prod/config.yaml.template` — явное значение
(например `90`) с комментарием, оператор видит и осознанно выбирает.

`AbstractJobStore.purge_old(retention_days: int) -> int` (новый
абстрактный метод, `store/base.py`):
- `SQLJobStore.purge_old()` — `DELETE FROM workflow_jobs WHERE status IN
  (COMPLETED, FAILED, TIMEOUT, CANCELLED) AND finished_at < now() -
  retention_days days`, возвращает число удалённых строк.
- `InMemoryJobStore.purge_old()` — no-op (`return 0`): `keep_completed`
  уже делает эквивалентную по смыслу эвикцию (`job_store.py:89-95`), второй
  механизм не нужен.

Вызов — периодическая задача через уже существующий
`OrchestratorScheduler` (`core/scheduler.py`), не новый компонент:
`self._scheduler.add_job(purge_task, IntervalTrigger(hours=24), id=
"retention_cleanup")` в `start()`, только если `config.jobs.retention_days
> 0`. Логирование числа удалённых записей на каждый прогон (видимость,
не тихая операция).

## [S7] Config + Fail-Fast Validation

`orchestrator/config.py::QueueConfig`:

```python
class QueueConfig(BaseModel):
    backend: str = "memory"  # memory | redis | sql
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 10
    redis_push_timeout: float = 5.0
    redis_pop_timeout: float = 1.0
    sql_poll_interval: float = 0.5
```

`orchestrator/main.py::create_queue()`:

```python
def create_queue(config):
    if config.queue.backend == "redis":
        return RedisQueue(...)
    if config.queue.backend == "sql":
        if config.jobs.persistence != "sql":
            raise ValueError(
                "queue.backend: sql requires jobs.persistence: sql — "
                "SQLQueue reads/writes the same workflow_jobs table as JobStore"
            )
        return SQLQueue(get_session_factory(), poll_interval=config.queue.sql_poll_interval)
    return InMemoryQueue()
```

## [S8] Deploy Template Changes

`deploy/prod/config.yaml.template`:

```yaml
queue:
  backend: sql  # было redis — устраняет at-most-once потерю джобов (P14), см. UPGRADE-v2.md

jobs:
  log_dir: /var/log/soar/jobs
  keep_completed: 100
  persistence: sql
  retention_days: 90  # явный выбор оператора — 0 хранил бы историю бесконечно
```

`redis`-сервис в `docker-compose.yml` можно оставить в деплое как опцию
(P14 не требует его физически убирать), но не как дефолт диспетчеризации
критичных workflows. Убирать секцию `redis:` из `docker-compose.yml` — вне
скоупа этого спека (не точечная правка, отдельное решение оператора при
следующей ревизии деплоя).

## [S9] Testing Strategy

- `test_sql_queue.py`: push/pop round-trip на `sqlite+aiosqlite:///:memory:`
  (тот же фикстур-паттерн, что `test_sql_job_store.py:16-25`); тест
  конкурентного claim — два параллельных `pop()` над одним PENDING-джобом,
  ровно один получает джоб, второй — `None`/следующий в очереди; тест, что
  `push()` не создаёт дублирующую запись поверх уже существующей
  `job_store.save()`.
- `test_main_job_store_factory.py`: `queue.backend: sql` + `jobs.
  persistence: memory` → `create_queue()` бросает `ValueError` при старте.
- `test_sql_job_store.py`: `purge_old()` — удаляет только
  COMPLETED/FAILED/TIMEOUT/CANCELLED старше порога, не трогает RUNNING/
  PENDING независимо от возраста.
- Regression: существующие `test_queue.py`, `test_redis_queue.py`,
  `test_job_store.py` проходят без изменений (контракты `AbstractJobQueue`/
  `AbstractJobStore` не меняются, только новая реализация + новый
  абстрактный метод с реализацией в обоих существующих классах).

## [S10] Success Criteria

- [ ] `SQLQueue` реализует `AbstractJobQueue`, claim атомарен на Postgres
      (`SKIP LOCKED`) и на SQLite (сериализация), проверено тестом на
      конкурентный `pop()`
- [ ] `push()` не создаёт лишней записи — переиспользует уже сохранённую
      `JobManager.enqueue()` запись
- [ ] `queue.backend: sql` без `jobs.persistence: sql` — явная ошибка при
      старте, не тихий недо-рабочий режим
- [ ] Partial-индекс `(status, triggered_at) WHERE status='PENDING'`
      добавлен миграцией, claim-запрос не деградирует с ростом числа
      COMPLETED-записей
- [ ] `jobs.retention_days` — дефолт `0` (выключено) на уровне схемы,
      явное значение в `deploy/prod/config.yaml.template`
- [ ] `purge_old()` реализован в `SQLJobStore`, no-op в `InMemoryJobStore`,
      вызывается по расписанию через существующий `OrchestratorScheduler`
      без нового компонента в деплое
- [ ] `deploy/prod/config.yaml.template` и `deploy/stage/config.yaml`
      переключены на `queue.backend: sql`
- [ ] Все существующие тесты очереди/джобстора проходят без изменений
