# Purge Job Log Files Alongside DB Retention (S5)

> Реализует S5 из `docs/concepts/BAGFIX_PLAN.md`. `jobs.retention_days`
> удаляет строки `workflow_jobs`, но не трогает файлы `.log` на диске —
> на любом проде с ненулевым retention (`deploy/prod`: 90 дней) диск
> гарантированно заполняется, а `log_path` осиротевших файлов теряется
> безвозвратно вместе с удалённой строкой.

## [S1] Problem

`SQLJobStore.purge_old()` (`orchestrator/store/sql_job_store.py:102-115`):

```python
async def purge_old(self, retention_days: int) -> int:
    threshold = datetime.now(UTC) - timedelta(days=retention_days)
    async with self._session_factory() as session:
        result = await session.execute(
            delete(JobRecord).where(
                JobRecord.status.in_(_TERMINAL_STATUSES),
                JobRecord.finished_at < threshold,
            )
        )
        await session.commit()
        count = result.rowcount or 0
    ...
    return count
```

`DELETE` не читает `log_path` перед удалением строки — файл под
`/var/log/soar/jobs/<workflow>/<job_id>.log`
(`orchestrator/core/job_manager.py:59-63::_make_log_path`) остаётся на
диске, но единственная ссылка на его путь (`JobRecord.log_path`) уже не
существует нигде — ни в БД, ни в памяти процесса. Файл не читаем через
API (`GET /logs/{id}` резолвит путь через job store по id — записи нет),
не удаляем никаким последующим прогоном `purge_old` (он работает по
строкам БД, не по файлам на диске), и не виден ничем, кроме прямого
доступа к файловой системе хоста.

Вызывается это периодической job'ой в `OrchestratorScheduler`
(`orchestrator/core/scheduler.py:22-32::_add_retention_job`,
`IntervalTrigger(hours=24)`) — на `deploy/prod`
(`retention_days: 90`, `config.yaml.template`) это значит: каждый день
чистятся строки БД старше 90 дней, а их файлы логов копятся на диске
**бессрочно**, без верхней границы, с первого дня эксплуатации.
Единственный workaround сегодня — ручная чистка файловой системы в обход
API, что ломает соответствие "что в БД, то и на диске" и требует
знания внутреннего формата пути.

## [S2] Solution

Собрать `log_path` всех попадающих под удаление записей **до** `DELETE`,
удалить файлы **после** успешного коммита транзакции (не до — если
`DELETE`/`commit` упадёт, файлы не должны быть уже стёрты для записей,
которые остались в БД):

```python
async def purge_old(self, retention_days: int) -> int:
    threshold = datetime.now(UTC) - timedelta(days=retention_days)
    async with self._session_factory() as session:
        to_delete = await session.execute(
            select(JobRecord.log_path).where(
                JobRecord.status.in_(_TERMINAL_STATUSES),
                JobRecord.finished_at < threshold,
                JobRecord.log_path.is_not(None),
            )
        )
        log_paths = [row[0] for row in to_delete if row[0]]

        result = await session.execute(
            delete(JobRecord).where(
                JobRecord.status.in_(_TERMINAL_STATUSES),
                JobRecord.finished_at < threshold,
            )
        )
        await session.commit()
        count = result.rowcount or 0

    for path in log_paths:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass  # уже удалён вручную/предыдущим неполным прогоном — не ошибка
        except OSError as e:
            logger.warning(f"Retention cleanup: failed to remove log file {path}: {e}")

    if count > 0:
        logger.info(f"Retention cleanup: purged {count} job records older than {retention_days}d")
    return count
```

Два отдельных `SELECT`+`DELETE` в одной сессии (не один `DELETE ...
RETURNING log_path`) — `RETURNING` не переносится один в один между
Postgres и SQLite одинаково просто через SQLAlchemy Core в текущем стиле
проекта (оба backend'а поддерживаются, см. `database.url` дефолт
SQLite/Postgres в проде); два запроса с идентичным `WHERE` — надёжнее
и переносимее, стоимость лишнего `SELECT` пренебрежимо мала относительно
частоты вызова (раз в 24 часа).

Ошибка удаления одного файла (права доступа, гонка с ручным вмешательством
оператора) **не должна** прерывать удаление остальных файлов или сам
cleanup-цикл — логируется и пропускается, согласно бюллету плана
("ошибки удаления файла логировать, не ронять cleanup"). Уже
существующий `_add_retention_job` в `scheduler.py:22-29` оборачивает весь
вызов `purge_old()` в `try/except`, логируя `Retention cleanup failed` —
эта внешняя защита остаётся, но теперь не нужна для файловых ошибок
(они не всплывают наружу как исключение), только для настоящих сбоев
самого `purge_old` (обрыв соединения с БД и т.п.).

### Осиротевшие файлы от предыдущих (уже случившихся) прогонов

Не в скоупе этого фикса — на инсталляциях, где `purge_old` уже отработал
до фикса, накопившиеся осиротевшие файлы (без соответствующей строки в
БД) не будут найдены новой версией (она ищет `log_path` **из ещё живых**
строк перед их удалением, не сканирует файловую систему на предмет
"чего нет в БД"). Разовая ручная чистка (`find /var/log/soar/jobs -mtime
+90 -delete` или аналог) — операторская задача, вне API/кода; можно
упомянуть в `deploy/prod/README.md` Day 2 operations как разовый шаг при
апгрейде на версию с этим фиксом, решить на этапе плана, нужно ли.

## [S3] `AbstractJobStore` — только `SQLJobStore` затронут

`InMemoryJobStore.purge_old()` (`orchestrator/store/job_store.py`) —
уже no-op по комментарию в `AGENTS.md` (`store/job_store.py`: "no-op") —
in-memory хранилище не переживает рестарт в принципе, retention
неприменим; этот фикс его не трогает. `AbstractJobStore.purge_old()`
интерфейс (`store/base.py`) не меняет сигнатуру — по-прежнему
`(retention_days: int) -> int`, возвращает количество удалённых
**записей** (не файлов) — не меняется контракт для вызывающей стороны
(`scheduler.py::_add_retention_job` логирует именно это число).

## [S4] Testing Strategy

`tests/orchestrator/store/test_sql_job_store.py`:

- **Новый** `test_purge_old_removes_log_files` — создать
  `JobRecord`/`WorkflowJob` с `finished_at` за пределами retention,
  `log_path`, указывающим на реальный временный файл (`tmp_path`),
  вызвать `purge_old()`, убедиться: строка удалена из БД **и** файл по
  `log_path` больше не существует на диске.
- **Новый** `test_purge_old_survives_missing_log_file` — запись с
  `log_path`, указывающим на несуществующий файл (уже удалён руками) →
  `purge_old()` не поднимает исключение, продолжает удалять остальные
  подходящие записи, возвращает корректный `count`.
- **Regression** `test_purge_old` (существующий, если есть) — записи
  моложе `retention_days` или не в терминальном статусе не удаляются ни
  из БД, ни на диске (файл не тронут).
- Тест на `log_path is None` (jobs без лога, если такое возможно) — не
  вызывает `os.remove(None)`/исключение.

## [S5] Success Criteria

- [ ] `purge_old()` удаляет файлы логов вместе со строками БД, в
      пределах того же вызова
- [ ] Порядок операций: собрать пути → удалить строки → закоммитить →
      удалить файлы (файлы не трогаются, если транзакция не
      закоммитилась)
- [ ] Ошибка удаления одного файла не прерывает cleanup остальных и не
      бросает исключение наружу — только `logger.warning`
- [ ] `InMemoryJobStore`/интерфейс `AbstractJobStore.purge_old()` не
      регрессируют
- [ ] На проде (`retention_days: 90`) диск больше не растёт
      неограниченно от логов джобов старше окна retention
