# Plan: Remove IRP integration; Tools discovery API

> Spec: `docs/compose/specs/2026-07-10-irp-settings-tools-refactor-design.md`

## Порядок: R1 (удаление) → R2 (tools API, test-first) → R3 (аудит, без кода) → полный прогон тестов → AGENTS.md

---

- [x] Write plan file

## R1: Удалить IRP-интеграцию

- [x] Удалить `soar/connectors/irp/` (`irp.py`, `__init__.py`, `irp.example.yml`)
- [x] Удалить `soar/workflows/alert_triage.py`, `soar/workflows/irp-events.py`, `soar/workflows/irp_reconcile.py`, `soar/workflows/respond_basic.py`
- [x] Удалить `soar/tools/irp_settings.py`, `soar/tools/irp_dispatch.py`, `soar/tools/triage_policy.py`
- [x] Удалить `tests/soar/test_irp_connector.py`, `tests/soar/test_irp_events_workflow.py`, `tests/soar/test_irp_reconcile.py`, `tests/soar/test_alert_triage_workflow.py`, `tests/soar/test_triage_policy.py`
- [x] `orchestrator/config.yaml` — удалить секцию `irp:`
- [x] `deploy/stage/config.yaml` — удалить секцию `irp:`
- [x] `soar/tools/watermark.py` + `tests/soar/test_watermark_store.py` — модуль остаётся (generic), докстринги/тестовые ключи очищены от IRP-специфики (`irp_reconcile`/`irp_seen:1` → `source_b`/`seen:1`)
- [x] `grep -rn "irp" soar/ tests/ orchestrator/` — подтверждено отсутствие висячих ссылок (единственное совпадение, `dirpath` в `connectors.py`, — ложное срабатывание подстроки)
- [x] `python -m pytest tests/soar/ tests/orchestrator/ -q` — зелёный (348 passed; 4 падения — pre-existing/environmental, воспроизведены на `main` через `git stash`, не мои)

## R2: Tools Discovery API

- [x] Тесты `tests/orchestrator/api/test_tools_api.py` (имя файла по конвенции соседних `test_actions_api.py`/`test_connectors_api.py`, не `test_tools.py` из черновика): `test_list_tools_finds_known_classes`, `test_get_tool_returns_docstring_and_signature`, `test_get_tool_unknown_404`, `test_parse_module_does_not_import`
- [x] RBAC-тест пропущен: ни один соседний `test_*_api.py` не тестирует роли по роутеру отдельно (RBAC тестируется централизованно в `test_auth_api.py`) — не вводил новый паттерн
- [x] Подтверждено red: тесты падали с `ValueError: "SoarConfig" object has no field "tools_dir"` до реализации
- [x] Реализация `orchestrator/api/tools.py`: `_signature()`, `_summary()`, `_parse_module()`, `GET /tools`, `GET /tools/{name}`
- [x] `orchestrator/config.py`: `SoarConfig.tools_dir: str = "soar/tools"`
- [x] `orchestrator/api/__init__.py` + `orchestrator/main.py`: `tools_router` экспортирован и подключён
- [x] `tests/orchestrator/api/conftest.py`: `config.soar.tools_dir` = `tmp_path / "tools"` (по образцу остальных `*_dir`)
- [x] `python -m pytest tests/orchestrator/api/test_tools_api.py -v` — 4 passed

## R3: Аудит API-поверхности

- [x] Таблица из спеки [S5] сверена с `orchestrator/api/*.py` — пробелов, кроме `/tools`, не найдено; изменений в `connectors.py`/`actions.py`/`workflows.py` не потребовалось

## Финал

- [x] Полный прогон: `python -m pytest tests/ -q` — 352 passed, 1 skipped, 4 failed (те же pre-existing/environmental)
- [x] `ruff check` файлов, тронутых в этой ветке — чисто (оставшиеся ruff-замечания в `conftest.py`/`subprocess_runner.py`/`job_store.py`/`active_directory.py`/`wazuh.py` — pre-existing, вне diff'а этой ветки)
- [x] `AGENTS.md`: убрана IRP из шапки и файлового дерева, добавлен `### Tools` в API Endpoints, добавлена запись v0.5.3 (откат IRP + Tools API), версия шапки документа поднята до v0.5.3
- [ ] Коммит на ветке `remove-irp-tools-api`
