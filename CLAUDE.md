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

Актуальные баги и Known Limitations — в [`docs/agents/known-limitations.md`](docs/agents/known-limitations.md).

Концепты верхнего уровня (карта проблем + реестр рисков, не заменяют спеки) — [`docs/concepts/`](docs/concepts/): [`UPGRADE.md`](docs/concepts/UPGRADE.md) (Agent Dev-Loop, этапы 1-3 реализованы), [`UPGRADE-v2.md`](docs/concepts/UPGRADE-v2.md) (pre-release ревью перед деплоем на живую инфру — P12/P13/P14/P16 реализованы в v0.12, P15/P17 приняты как остаточный риск/чеклист без кода).

**Открытые баги — [`docs/concepts/BAGFIX_PLAN.md`](docs/concepts/BAGFIX_PLAN.md)** (трек по итогам ревью 2026-07-27, отчёт — [`docs/compose/reports/prod-readiness-review-2026-07-27.md`](docs/compose/reports/prod-readiness-review-2026-07-27.md)). B1–B4 — блокеры пилота, до их закрытия на живую инфру не выходим.

Активные спеки (написаны, не выполнены):

- [`docs/compose/specs/2026-07-03-v06-upgrade-design.md`](docs/compose/specs/2026-07-03-v06-upgrade-design.md) — per-workflow метрики, dry-run конвенция (Feature 1/`CachedHttpClient` реализована как `HttpClient` в v0.12, см. `2026-07-27-http-client-design.md` и пометку в файле; Feature 2/3 остаются неактивными)
- [`docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md`](docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md) — `soarctl`: on-site установка из git + `update` без пересоздания БД (расширяет `2026-07-22-deploy-cli-design.md`, не входит в `UPGRADE-v2.md`)

`2026-07-03-bugfixes-design.md` — не активен, все 7 багов исправлены в v0.5 (см. `CHANGELOG.md`), спек оставлен как референс.

## Что читать, что не читать

**Читать:** `soar/`, `orchestrator/`, `tests/`
**Не читать:** `ui/`, `deploy/` — вспомогательное

При поиске по кодовой базе — использовать Grep/Glob, не читать файлы целиком без причины.

## Ключевые паттерны (детали — в AGENTS.md)

- **Workflow lifecycle:** `JobManager.enqueue()` → `Worker._execute()` → `SubprocessRunner` → `soar.runner` subprocess
- **Workflow key:** имя файла без `.py` (не имя класса) — `WorkflowRegistry` использует `module_name` как ключ
- **Connector lazy init:** `_ensure_connected()` при первом вызове метода
- **Git auto-commit:** любое изменение файла через API коммитится через `GitManager`
- **Auth:** JWT+RBAC с v0.5.1, но опционален — `auth.secret_key = ""` в config → анонимный admin (Docker-сетевое доверие); на deploy/stage включена с v0.9
- **Dry-run:** `context["dry_run"] = True` в `POST /jobs` → workflow пропускает мутации

## Чего не делать

- Не рефакторить вне задачи — только минимальный фикс/фича
- Не писать комментарии, объясняющие что делает код — только WHY если неочевидно
- Не обращаться к `_metas`, `_redis`, `_ensure_connected()` из API роутов — только публичные методы
- Не импортировать `load_workflow_metas` из `orchestrator.main` — вынести в `core/` при следующем рефакторе
- Не обновлять AGENTS.md заранее — только после выполнения задачи
