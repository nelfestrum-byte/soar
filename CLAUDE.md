# CLAUDE.md — рабочие инструкции для этого проекта

Основной источник истины: **[AGENTS.md](AGENTS.md)** — читай его первым делом в любой сессии.

## Что это за проект

Минималистичный SOAR без LLM. Детерминированные автоматические расследования на ECS-схеме, автоматическое закрытие стандартных кейсов с FP.

Два компонента:
- `soar/` — коннекторы, actions, workflows (Python-пакет)
- `orchestrator/` — FastAPI оркестратор (очередь, воркеры, планировщик, git-версионирование)

`ui/` — стенд для ручного тестирования, **не часть продукта**.

## Обязательный порядок работы

**Перед написанием кода — написать спек.** Всегда.

```
docs/compose/specs/YYYY-MM-DD-<feature>-design.md   ← сначала
docs/compose/plans/YYYY-MM-DD-<feature>.md           ← потом
docs/compose/reports/<feature>.md                    ← после завершения
```

Формат спеков — как в существующих примерах: `[S1] Problem`, `[S2] Solution`, ...
Формат планов — checkbox-и `- [ ]`, test-first (сначала падающий тест).

## Текущее состояние

Актуальные баги и Known Limitations — в `AGENTS.md#known-limitations`.

Активные спеки (написаны, не выполнены):
- [`docs/compose/specs/2026-07-03-bugfixes-design.md`](docs/compose/specs/2026-07-03-bugfixes-design.md) — 7 багов из ревью (cancel race, mysql sql, redis concurrency, result_data, rate limiter, ssrf dns, private fields)
- [`docs/compose/specs/2026-07-03-v06-upgrade-design.md`](docs/compose/specs/2026-07-03-v06-upgrade-design.md) — CachedHttpClient, per-workflow метрики, dry-run конвенция

## Что читать, что не читать

**Читать:** `soar/`, `orchestrator/`, `tests/`
**Не читать:** `ui/`, `deploy/` — вспомогательное

При поиске по кодовой базе — использовать Grep/Glob, не читать файлы целиком без причины.

## Ключевые паттерны (детали — в AGENTS.md)

- **Workflow lifecycle:** `JobManager.enqueue()` → `Worker._execute()` → `SubprocessRunner` → `soar.runner` subprocess
- **Workflow key:** имя файла без `.py` (не имя класса) — `WorkflowRegistry` использует `module_name` как ключ
- **Connector lazy init:** `_ensure_connected()` при первом вызове метода
- **Git auto-commit:** любое изменение файла через API коммитится через `GitManager`
- **No auth до v0.8:** сервис в Docker-сети, авторизации нет
- **Dry-run:** `context["dry_run"] = True` в `POST /jobs` → workflow пропускает мутации

## Чего не делать

- Не рефакторить вне задачи — только минимальный фикс/фича
- Не писать комментарии, объясняющие что делает код — только WHY если неочевидно
- Не обращаться к `_metas`, `_redis`, `_ensure_connected()` из API роутов — только публичные методы
- Не импортировать `load_workflow_metas` из `orchestrator.main` — вынести в `core/` при следующем рефакторе
- Не обновлять AGENTS.md заранее — только после выполнения задачи
