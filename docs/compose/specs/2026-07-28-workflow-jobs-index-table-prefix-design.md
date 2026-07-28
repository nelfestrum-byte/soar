# Pending-Index on Fresh Installs + Migration `table_prefix` Fix (S6)

> Реализует S6 из `docs/concepts/BAGFIX_PLAN.md`. Партиальный индекс из
> P14 (`docs/compose/specs/2026-07-27-sql-job-queue-design.md`) не
> создаётся на штатной последовательности установки прода; смежно —
> Alembic-миграции игнорируют `database.table_prefix` там, где имя
> таблицы — не единственный `prefixed(...)`-вызов в файле.

## [S1] Problem

### [S1.1] Индекс не создаётся на `soarctl up && soarctl migrate --fresh`

Штатная последовательность установки прода (`AGENTS.md`, `deploy/prod/
README.md`): `soarctl up` (поднимает контейнеры, `create_all()`
срабатывает на старте оркестратора и создаёт отсутствующие таблицы) →
`soarctl migrate --fresh` → `deploy/soarctl_lib/migrate.py::stamp_head()`
→ `alembic stamp head`. `stamp head` **не выполняет DDL** — только
проставляет ревизию в `alembic_version` как применённую, ничего не
создавая. Партиальный индекс `ix_workflow_jobs_pending_triggered_at`
объявлен только в миграции `42fbd47b0d46_add_workflow_jobs_pending_index.py`
(`op.create_index(...)`), не в модели
(`orchestrator/store/models.py::JobRecord`, где явный комментарий:
"a partial index ... is added via alembic migration (**not declared
here**)"). `create_all()` строит схему из `Base.metadata` — если индекс
не в модели, `create_all()` его не создаёт. Итог: любая свежая
установка прода по документированному пути заканчивается без индекса,
на который рассчитан `SQLQueue.pop()` (см. P14 [S4]/[S5] в
`sql-job-queue-design.md`) — claim-запрос остаётся корректным
функционально, но перестаёт быть дешёвым при накоплении исторических
`COMPLETED`/`FAILED` строк, ровно то, ради чего индекс добавлялся.

`--upgrade` (не `--fresh`) создал бы индекс корректно — но это не
штатный путь для **первой** установки (см. `docs/agents/config-reference.md`/
`AGENTS.md` "Landmine": `upgrade head` на новую таблицу, уже созданную
`create_all()`, падает `DuplicateTableError` для миграций, добавляющих
таблицу целиком; для этой конкретной миграции таблица уже существует,
добавляется только индекс — здесь `upgrade head` **не упал** бы, но
операторский чеклист один на все миграции: "новая инсталляция → `--fresh`
всегда", не "проверить каждую миграцию, добавляет ли она таблицу
целиком или только индекс к существующей".

### [S1.2] `table_prefix` игнорируется в двух миграциях, не в одной

Докстринг `42fbd47b0d46_*.py:12-15` утверждает, что "existing migrations
(ea0bb43fc071, 3067dea7c75b) already don't account for
`database.table_prefix`". Проверка обеих: `ea0bb43fc071_initial_auth_and_
jobs_tables.py` **уже корректно** использует `prefixed()`/`fk()` на
каждой таблице/индексе (`op.create_table(prefixed('workflow_jobs'), ...)`,
`op.create_index(f"ix_{prefixed('workflow_jobs')}_status", ...)` и т.д.)
— докстринг здесь неточен, эта миграция не затронута багом.
`3067dea7c75b_add_audit_log_table.py`, напротив, **действительно**
использует литеральный `'audit_log'` без `prefixed()` во всех
`op.create_table`/`op.create_index`/`op.drop_*` вызовах — тот же класс
бага, что и новая `42fbd47b0d46` (литеральный `'workflow_jobs'` в
`op.create_index("...", "workflow_jobs", ...)`), просто не был замечен
раньше, потому что `alembic upgrade head` целиком (не `--fresh`) в
`deploy/stage` (`table_prefix: "stage_"`) до сих пор не был реально
прогнан на этой конкретной таблице post-P14 (audit_log — из более ранней
миграции, обычно уже присутствует до того, как кто-то трогает
`table_prefix`).

Итог для `deploy/stage` (`table_prefix: "stage_"`, единственная
инсталляция в проекте с непустым префиксом сегодня): если когда-либо
понадобится `alembic upgrade head` (не `--fresh`) на этой таблице —
Alembic создаст/тронет `audit_log`/`ix_workflow_jobs_pending_triggered_at`
без префикса, тогда как приложение (`Base.metadata`, собранная после
`configure_table_prefix("stage_")` в `alembic/env.py:25-26`) ожидает
`stage_audit_log`/индекс на `stage_workflow_jobs`. DDL применяется не к
той таблице, что использует приложение.

## [S2] Solution

### [S2.1] Индекс — объявить в модели, чтобы `create_all()` создавал его

`JobRecord` (`orchestrator/store/models.py`) получает `Index(...)` как
часть `__table_args__`, вместо комментария "не declared here":

```python
from sqlalchemy import Index

class JobRecord(Base):
    __tablename__ = prefixed("workflow_jobs")
    __table_args__ = (
        Index(
            "ix_workflow_jobs_pending_triggered_at",
            "status", "triggered_at",
            postgresql_where=text("status = 'PENDING'"),
            sqlite_where=text("status = 'PENDING'"),
        ),
    )
    ...
```

`create_all()` теперь создаёт индекс вместе с таблицей на любой свежей
инсталляции, независимо от того, идёт ли следом `stamp head` или
`upgrade head` — фикс не зависит от выбора оператора. Индекс с этим же
именем **не переименовывается** — совпадает с тем, что уже создаёт
существующая миграция `42fbd47b0d46` для случая **апгрейда** старой
инсталляции (таблица уже была, `create_all()` её не трогает, DDL
добавления индекса реально нужен и должен продолжать идти через
`alembic upgrade head`). Модель и миграция теперь описывают один и тот
же индекс двумя путями для двух разных сценариев (fresh vs upgrade),
намеренно — не дублирование, которое надо устранять, а два независимых
триггера одного результата.

Имя индекса — literal `"ix_workflow_jobs_pending_triggered_at"`, не
`f"ix_{prefixed('workflow_jobs')}_pending_triggered_at"`
как в `ea0bb43fc071`'s comment требует (Postgres index namespace —
per-schema, не per-table, риск коллизии между инстансами с разным
`table_prefix`, шарящими одну БД). Поправить на `Index(f"ix_{prefixed
('workflow_jobs')}_pending_triggered_at", ...)` и в модели, и — отдельным
шагом — в существующей миграции `42fbd47b0d46` (см. [S2.2]), чтобы имя
индекса совпадало между двумя путями создания; сегодняшнее имя в
миграции литеральное, тоже без префикса — тот же баг, что и имя таблицы,
чинится тем же изменением.

### [S2.2] Обе миграции — `prefixed()` вместо литеральных имён

`42fbd47b0d46_add_workflow_jobs_pending_index.py`:

```python
from orchestrator.db.base import prefixed

def upgrade() -> None:
    op.create_index(
        f"ix_{prefixed('workflow_jobs')}_pending_triggered_at",
        prefixed("workflow_jobs"),
        ["status", "triggered_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
        sqlite_where=sa.text("status = 'PENDING'"),
    )

def downgrade() -> None:
    op.drop_index(
        f"ix_{prefixed('workflow_jobs')}_pending_triggered_at",
        table_name=prefixed("workflow_jobs"),
    )
```

`3067dea7c75b_add_audit_log_table.py` — та же правка на все
`create_table('audit_log', ...)`/`create_index(op.f('ix_audit_log_*'),
'audit_log', ...)`/`drop_*` вызовы, заменить литерал `'audit_log'` на
`prefixed('audit_log')`, индексные имена — на `f"ix_{prefixed
('audit_log')}_..."` вместо `op.f('ix_audit_log_...')`.

Обе миграции полагаются на то, что `alembic/env.py:25-26` уже вызывает
`configure_table_prefix(_soar_config.database.table_prefix)` **до**
запуска любой миграции — `prefixed()` внутри файла миграции резолвится
корректно на момент `alembic upgrade`/`downgrade`, тот же механизм, что
уже работает для `ea0bb43fc071`. Правка существующих (уже
"применённых" на некоторых инсталляциях) файлов миграций безопасна: она
не меняет `revision`/`down_revision` (ревизия остаётся той же по хэшу
идентификатора, не по содержимому), инсталляции, где эти миграции уже
физически применены с литеральным именем на пустом `table_prefix`,
не затронуты (пустой префикс — `prefixed(x) == x`, поведение не
меняется); затронуты только будущие применения (`upgrade head`) на
инсталляции с непустым `table_prefix`, которые сегодня ломаются молча.

### [S2.3] Что не чинится в этом треке

`ea0bb43fc071` уже корректна — не трогается. Известное ограничение
"Postgres index namespace — per-schema" — уже задокументировано
собственным комментарием в этой миграции, не новый риск.
Мультиинстансность как продуктовая фича (несколько логических
инстансов на одной физической БД с разными `table_prefix`) остаётся вне
scope `soarctl` (known-limitation #8, `docs/agents/known-limitations.md`)
— этот трек чинит только то, что миграции **сами по себе** корректно
уважают `table_prefix`, когда он задан вручную (как в `deploy/stage`),
не добавляет CLI-поддержку управления несколькими инстансами.

## [S3] Testing Strategy

`tests/orchestrator/store/test_models.py` (или новый файл, если
индексов там ещё не тестируют):

- **Новый** `test_create_all_creates_pending_index` — `create_all()` на
  in-memory/temp SQLite engine, проверить через `sqlite_master`
  (`SELECT name FROM sqlite_master WHERE type='index'`), что
  `ix_workflow_jobs_pending_triggered_at` (или с префиксом, если тест
  гоняется с `table_prefix`) существует после `create_all()`, без
  запуска Alembic вообще.
- **Новый** (Postgres-only, если в CI есть Postgres — иначе
  документировать как манульную проверку) — то же через
  `information_schema`/`pg_indexes`, убедиться, что
  `postgresql_where` реально применился (частичный индекс, не полный).

`tests/` для миграций (если есть существующий паттерн прогона
Alembic в тестах — проверить `tests/orchestrator/` на наличие; если нет,
добавить минимальный):

- **Новый** тест: `configure_table_prefix("test_")`,
  `alembic upgrade head` на временную SQLite БД → все таблицы/индексы из
  `3067dea7c75b`/`42fbd47b0d46` носят префикс `test_`, не голые имена.
  Regression-тест ровно на баг из [S1.2].

## [S4] Success Criteria

- [ ] Партиальный индекс на `(status, triggered_at) WHERE status =
      'PENDING'` существует после `soarctl up && soarctl migrate --fresh`
      на свежей инсталляции — не только после `--upgrade`
- [ ] `42fbd47b0d46` и `3067dea7c75b` используют `prefixed()`
      последовательно с `ea0bb43fc071` — ни одна миграция не создаёт
      таблицу/индекс без префикса, когда `database.table_prefix` не пуст
- [ ] Имя индекса идентично между путём `create_all()` (модель) и путём
      `alembic upgrade head` (миграция) — не создаётся двух разных
      индексов с разными именами на одной таблице
- [ ] `deploy/stage` (`table_prefix: "stage_"`) — `alembic upgrade head`
      (если когда-либо запущен вместо `--fresh`) применяет DDL к
      `stage_audit_log`/`stage_workflow_jobs`, не к голым именам
- [ ] `docs/concepts/UPGRADE-v2.md` P14 и
      `docs/compose/specs/2026-07-27-sql-job-queue-design.md` [S5]
      обновлены — партиальный индекс гарантированно создаётся на любой
      установке, не только апгрейд-пути (см. D8, правится вместе с этим
      треком)
