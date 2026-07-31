# Report: Fix workflow → action → connector pattern (Д1+Д2), + Д3, Н1–Н4

Спека (Д1+Д2): `docs/compose/specs/2026-07-31-workflow-connector-scoping-design.md`
План: `docs/compose/plans/2026-07-31-workflow-connector-scoping.md`
Источник: `docs/compose/reports/manual-qa-prod-onsite.md` §3.

## Что сделано

### Д1 — порядок инициализации реестров (`soar/runner.py`)

Переставлен порядок трёх `*.init()` вызовов: было
`workflows → connectors → actions`, стало
`connectors → actions → workflows`. Позиция сборки
`tools.http_client`/`tools.http_client_sync` (перед всеми тремя) не тронута.
Обоснование порядка — [S2] спеки: `connectors.init()` должен отработать
первым, чтобы `_install_shims()` успел установить `soar.connectors.<type>`
до того, как что-либо (action или workflow) попытается верхнеуровнево
импортировать из него; `actions.init()` — вторым, так как action сам может
верхнеуровнево импортировать коннектор; `workflows.init()` — последним.

### Д2 — транзитивное разрешение connector-usage через actions

`orchestrator/core/introspect.py::parse_connector_usage` получил новый
опциональный параметр `actions_dir: str | Path | None = None` и внутренний
`_visited: set[Path] | None = None`. При обнаружении верхнеуровневого
`from soar.actions.<module> import ...` и заданном `actions_dir` — функция
рекурсивно парсит `actions_dir/<module>.py` тем же AST-сканом (без
`importlib`, инвариант "никогда не импортирует" не нарушен). Каждая
рекурсия обёрнута в собственный `try/except (OSError, SyntaxError,
UnicodeDecodeError)` — сломанный или отсутствующий action-файл не обнуляет
остальные находки того же воркфлоу. `_visited` (множество резолвленных
путей) защищает от циклов импортов между action-файлами.

`orchestrator/core/subprocess_runner.py::build_scoped_config` теперь
передаёт `actions_dir=soar_cfg.get("actions_dir")` в
`parse_connector_usage`. Докстринги обеих функций обновлены — заменена
формулировка "at workflow module top-level" на описание транзитивного
обхода через `soar.actions.*`.

### Д3 — `GET /tools/{name}` 404 для singleton-записей

`orchestrator/api/tools.py::get_tool` — если запрошенное имя есть в
`__all__`, но не найдено ни в одном `parse_classes(py_file)` (не класс —
синглтон вроде `http_client`/`seen_store`), возвращается тот же
синтетический словарь `{"name": name, "module": "__init__", "summary": ""}`,
что уже возвращал `list_tools` для таких имён, вместо падения в `404`.
Имена вне `__all__` по-прежнему дают `404` (regression-тест
`test_get_tool_unknown_404` не тронут).

### Н1–Н4 + известное ограничение #6 — документация

- **Н1** — `docs/agents/api-reference.md`: добавлена строка, явно
  указывающая, что `PUT /workflows/{name}/code`, `PUT /actions/{name}`,
  `PUT /connectors/{name}/code` принимают raw source как тело запроса, не
  JSON-обёртку (подтверждено чтением `await request.body()` в
  `orchestrator/api/workflows.py`).
- **Н2** — там же: явно зафиксировано, что поле типа воркфлоу называется
  `type` (подтверждено `orchestrator/api/workflows.py:97`), не
  `workflow_type` — с уточнением, что `workflow_type` — отдельное поле
  внутренней модели `WorkflowJob`, не путать.
- **Н3** — `docs/compose/plans/2026-07-31-manual-qa-prod-onsite.md` Phase
  3.2: `from soar.tools.http_client import http_client_sync` →
  `from soar.tools import http_client_sync` (реально определён в
  `soar/tools/__init__.py`) — в обоих местах файла (вступление секции +
  пример кода).
- **Н4** — тот же план, раздел про негативные кейсы: убрана формулировка
  про единый `SOAR_WEBHOOK_TOKEN` из `deploy/prod/.env`, заменена описанием
  реального механизма — токен per-workflow, генерируется
  `secrets.token_urlsafe(32)` при создании воркфлоу
  (`orchestrator/api/workflows.py:54`), сверяется через
  `secrets.compare_digest` (`orchestrator/api/webhooks.py:26-27`).
- **Известное ограничение #6** (`docs/agents/known-limitations.md`) —
  дополнено: тот же корень (JWT payload без username) распространяется на
  `git_author()` (`orchestrator/audit/service.py:12-16`, подтверждено
  чтением — `user.username or f"user-{user.id}"`, а `CurrentUser.username`
  для JWT-акторов не заполняется, см. `orchestrator/auth/dependencies.py`)
  — git commit author для JWT-пользователей подписывается как
  `user-<id>@soar.local`, не логином.

## Изменённые файлы

- `soar/runner.py` — порядок `*.init()`.
- `orchestrator/core/introspect.py` — `parse_connector_usage` (новый
  `actions_dir`/`_visited`, рекурсия, докстринг).
- `orchestrator/core/subprocess_runner.py` — `build_scoped_config`
  передаёт `actions_dir`, докстринг.
- `orchestrator/api/tools.py` — `get_tool` синтетическая ветка.
- `docs/agents/api-reference.md`, `docs/agents/known-limitations.md`,
  `docs/compose/plans/2026-07-31-manual-qa-prod-onsite.md` — Н1–Н4 + #6.
- Тесты: `tests/soar/test_runner.py`, `tests/orchestrator/core/test_introspect.py`,
  `tests/orchestrator/test_subprocess_runner_env.py`,
  `tests/orchestrator/api/test_tools_api.py`.

## Test-first подтверждение

Новые тесты запускались против кода до фикса там, где это осмысленно
воспроизводило баг:

- `test_wrong_registry_init_order_fails_to_register_workflow` (Д1,
  негативный тест на порядок) — написан и подтверждён как воспроизводящий
  сценарий независимо от `runner.py` (использует свежие инстансы реестров,
  не сам `runner.py`), поэтому проходит как до, так и после фикса `runner.py`
  — он пинит сам факт "неправильный порядок не регистрирует воркфлоу", а не
  состояние `runner.py`. `test_runner_initializes_connectors_and_actions_before_workflows`
  (source-position assert) — этот тест лежал бы красным на исходном
  `runner.py` (`workflows.init` перед `connectors.init`/`actions.init`) —
  подтверждено содержимым `git diff` (строки переставлены).
- `test_get_tool_returns_synthetic_entry_for_non_class_singleton` (Д3) —
  запущен до фикса `get_tool`: `FAILED` (404 вместо 200), затем после
  фикса — `PASSED`.
- Д2-тесты (`test_parse_connector_usage_follows_action_import_transitively`
  и остальные пять) написаны против нового API `parse_connector_usage`
  сразу вместе с реализацией — сигнатура (`actions_dir`) не существовала
  до этой сессии, "красного" прогона по старому коду не было и не
  требовалось (сама функция не принимала параметр).

## Результат после фикса

```
tests/soar/test_runner.py — 15 passed
tests/orchestrator/core/test_introspect.py — 24 passed
tests/orchestrator/test_subprocess_runner_env.py — 15 passed, 1 skipped
tests/orchestrator/api/test_tools_api.py — 8 passed
```

Полный набор: `python -m pytest tests/ -q` →
**822 passed, 3 failed, 9 skipped**. Три падения —
`tests/orchestrator/test_redis_integration.py` (`test_redis_integration_push_pop`,
`test_redis_integration_multiple_jobs`, `test_redis_integration_clear`) —
преэкзистентные, требуют живой Redis-сервер, недоступный в этом окружении;
не связаны с этим изменением (тот же паттерн падений, что и в отчётах
предыдущих версий, например v0.13/v0.20).

`ruff check` на всех изменённых файлах — чисто.

## Success Criteria — статус

- [x] Воркфлоу с верхнеуровневым `from soar.actions.<name> import <func>`
      успешно регистрируется — покрыто
      `test_correct_registry_init_order_registers_workflow_with_transitive_action_import`.
- [x] Тот же воркфлоу получает в scoped `connectors_dir` credentials
      коннектора, используемого транзитивно через action — покрыто
      `TestBuildScopedConfig::test_scopes_transitively_through_action_import`.
- [x] `parse_connector_usage(path)` без `actions_dir` ведёт себя как раньше
      — все 5 исходных тестов зелёные без изменений.
- [x] Сломанный/отсутствующий action-файл не обрушивает скан и не обнуляет
      прямые импорты — покрыто `test_parse_connector_usage_missing_action_file_is_skipped`,
      `test_parse_connector_usage_broken_action_file_does_not_abort_scan`.
- [x] Цикл импортов между actions не даёт `RecursionError` — покрыто
      `test_parse_connector_usage_action_import_cycle_does_not_recurse_infinitely`.
- [x] `docs/agents/*.md` сверены и поправлены (Н1/Н2 в api-reference.md,
      #6 в known-limitations.md).
- [ ] Ручной E2E повтор Phase 5-7 из
      `docs/compose/plans/2026-07-31-manual-qa-prod-onsite.md` на
      пересобранном стенде — **не выполнен в этой сессии** (требует живой
      Docker-стенд; вне охвата раздела "Не читать: deploy/" и текущей
      рабочей среды). Три пункта из "Что не покрыто" отчёта
      (`connector.call` audit-событие в логе джобы, редакция kwargs в
      реальном логе, повторное исполнение restored-кода) остаются
      неподтверждёнными на реальном контейнере — код-путь и юнит/интеграционные
      тесты (моки `asyncio.create_subprocess_exec`, реальные AST-фикстуры)
      подтверждают исправление, но не заменяют полный E2E повтор на
      Docker-стенде.

## Out of scope

- Version bump / `CHANGELOG.md`/`AGENTS.md` version history entry — этот
  фикс не рассматривается как отдельный релиз ENTITY-MODEL-плана (в отличие
  от Фаз 1–4); краткая строка #6 в `AGENTS.md`'s "Known limitations" (п.443)
  остаётся достаточной как summary, полное описание — в
  `known-limitations.md`.
- Ручной E2E повтор на живом Docker-стенде — см. Success Criteria выше.
