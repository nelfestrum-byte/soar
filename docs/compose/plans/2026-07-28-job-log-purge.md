# Plan: Purge Job Log Files Alongside DB Retention (S5)

Спека: `docs/compose/specs/2026-07-28-job-log-purge-design.md`

## Tests first

- [x] Добавить `test_sql_job_store_purge_old_removes_log_files` в
      `tests/orchestrator/store/test_sql_job_store.py` — сохранить job с
      терминальным статусом, `finished_at` за пределами retention и
      `log_path`, указывающим на реальный файл в `tmp_path`; вызвать
      `purge_old()`; убедиться, что строка удалена из БД **и** файл больше
      не существует на диске. Подтвердить, что тест падает на текущем коде
      (файл остаётся).
- [x] Добавить `test_sql_job_store_purge_old_survives_missing_log_file` —
      запись с `log_path` на несуществующий файл → `purge_old()` не
      поднимает исключение, возвращает корректный `count`, остальные
      подходящие записи удаляются.
- [x] Добавить `test_sql_job_store_purge_old_ignores_null_log_path` — job
      без `log_path` (None) под retention → `purge_old()` не падает на
      `os.remove(None)`, строка удаляется.
- [x] Подтвердить, что существующие
      `test_sql_job_store_purge_old_deletes_only_terminal_statuses_past_threshold`
      и `test_sql_job_store_purge_old_returns_zero_when_nothing_old`
      остаются зелёными без изменений.

## Implementation

- [x] Добавить `import os` в `orchestrator/store/sql_job_store.py`.
- [x] Заменить тело `purge_old()` на версию из спеки [S2]: `SELECT
      JobRecord.log_path` под тем же `WHERE` до `DELETE`, затем
      существующий `DELETE`+`commit` без изменений, затем удаление файлов
      по собранным путям после коммита — `FileNotFoundError` игнорируется,
      прочий `OSError` логируется через `logger.warning`, не поднимается
      наружу.
- [x] Не менять `AbstractJobStore`/`InMemoryJobStore` — вне скоупа ([S3]).

## Verification

- [x] `python -m pytest tests/orchestrator/store/ -v` — все зелёные,
      включая 3 новых.
- [x] Полный `python -m pytest tests/ -q` — сравнить с базовым прогоном на
      немодифицированном дереве; ровно одно известное несвязанное падение
      (`tests/soar/tools/test_openapi.py::test_generate_config`), новых
      падений нет.

## Report

- [x] Написать `docs/compose/reports/job-log-purge.md` после завершения.
