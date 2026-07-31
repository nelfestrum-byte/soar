# Plan: Fix workflow → action → connector pattern + point fixes (Д1, Д2, Д3, Н1–Н4, #6)

Источник: `docs/compose/reports/manual-qa-prod-onsite.md`.
Спека (Д1+Д2): `docs/compose/specs/2026-07-31-workflow-connector-scoping-design.md`.
Д3 и документация — точечные правки без отдельной спеки (см. правило
`BAGFIX_PLAN.md` для M/D-уровня: мелкие/документационные пункты идут
напрямую, без цикла specs/plans/reports).

**Порядок:** Д1 → Д2 в одном заходе (одна цепочка, промежуточное состояние
"починен только Д1" всё ещё не даёт рабочего actions-паттерна — см. спеку
[S1]). Д3 и документация — независимы, можно параллельно.

---

## Часть 1 — Д1: порядок инициализации реестров

### Тесты первыми (`tests/soar/test_runner.py`)

- [ ] Новый тест (или расширение `test_runner_assigns_http_client_before_registry_init`):
      source-position assert — `connectors.init(external_dir=` и
      `actions.init(external_dir=` встречаются в `inspect.getsource(runner)`
      раньше `workflows.init(external_dir=`.
- [ ] Новый интеграционный тест на свежих инстансах (не process-global
      singletons) `ConnectorRegistry()`/`ActionsRegistry()`/`WorkflowRegistry()`:
      `tmp_path`-фикстуры `connectors/qa_httpbin/{qa_httpbin.py, qa_httpbin.yml}`,
      `actions/check_qa_ip.py` (top-level `from soar.connectors.qa_httpbin import x`),
      `workflows/qa_manual_test.py` (top-level `from soar.actions.check_qa_ip
      import check_qa_ip`). Порядок connectors → actions → workflows →
      `workflow_registry.get_class("qa_manual_test") is not None`.
- [ ] Companion негативный тест: те же фикстуры, но `WorkflowRegistry().init()`
      вызван без предварительной инициализации connector/action реестров той
      же сессии → `get_class("qa_manual_test") is None`. Пинит именно баг,
      найденный в QA (без этого теста первый тест мог бы быть "случайно
      зелёным" независимо от порядка).

### Implementation (`soar/runner.py`)

- [ ] Переставить порядок вызовов: `connectors.init(...)` → `actions.init(...)`
      → `workflows.init(...)` (было: workflows → connectors → actions).
      Позиция `tools.http_client`/`tools.http_client_sync` присвоений — не
      трогать, они уже стоят раньше всех трёх (см.
      `2026-07-28-http-client-init-order-design.md`).

---

## Часть 2 — Д2: транзитивное разрешение connector-usage через actions

### Тесты первыми (`tests/orchestrator/core/test_introspect.py`)

- [ ] `test_parse_connector_usage_follows_action_import_transitively`
- [ ] `test_parse_connector_usage_without_actions_dir_ignores_action_imports`
      (regression — дефолтное поведение без нового параметра не меняется)
- [ ] `test_parse_connector_usage_combines_direct_and_transitive_imports`
- [ ] `test_parse_connector_usage_missing_action_file_is_skipped`
- [ ] `test_parse_connector_usage_broken_action_file_does_not_abort_scan`
- [ ] `test_parse_connector_usage_action_import_cycle_does_not_recurse_infinitely`
- [ ] Прогнать существующие 5 тестов `test_parse_connector_usage_*` без
      изменений — подтвердить, что сигнатура осталась обратно совместимой
      (`actions_dir` опционален, по умолчанию `None`)

### Тесты первыми (`tests/orchestrator/test_subprocess_runner_env.py`)

- [ ] `TestBuildScopedConfig::test_scopes_transitively_through_action_import`
      — workflow → action → connector, assert scoped `connectors_dir`
      содержит нужный instance (паттерн как в `test_scopes_to_only_used_instance`)

### Implementation

- [ ] `orchestrator/core/introspect.py::parse_connector_usage` — добавить
      параметр `actions_dir: str | Path | None = None`, внутренний
      `_visited: set[Path] | None = None` для защиты от циклов; при
      обнаружении `from soar.actions.<module> import ...` и заданном
      `actions_dir` — рекурсивно парсить `actions_dir/<module>.py`, каждую
      рекурсию оборачивать в собственный `try/except (OSError, SyntaxError,
      UnicodeDecodeError)`, не абортить весь скан целиком. См. спеку [S3]
      за полным псевдокодом.
- [ ] Обновить докстринг `parse_connector_usage` — заменить формулировку "at
      workflow module top-level" на описание транзитивного обхода через
      `soar.actions.*`; сохранить утверждение "Never imports the module".
- [ ] `orchestrator/core/subprocess_runner.py::build_scoped_config` — передать
      `actions_dir=soar_cfg.get("actions_dir")` в вызов `parse_connector_usage`.
      Обновить докстринг (параграф про "workflows that only use old registry
      form" — уточнить, что "directly imports" теперь означает "directly, or
      transitively through `soar.actions.*` imports it uses").

---

## Часть 3 — Д3: `GET /tools/{name}` 404 для singleton-записей (точечный фикс)

**Где:** `orchestrator/api/tools.py:41-53` (`get_tool`).

**Суть:** `get_tool` ищет только среди `parse_classes` — синглтоны
(`http_client`, `http_client_sync`, `seen_store`, `watermark_store`) не
являются классами, их имя не совпадает ни с одним `cls["name"]`. Синтетическая
ветка, которая уже есть в `list_tools` (`orchestrator/api/tools.py:35-37`,
`{"name": name, "module": "__init__", "summary": ""}`), в `get_tool` просто
отсутствует.

- [ ] Тест (`tests/orchestrator/api/test_tools_api.py`):
      `test_get_tool_returns_synthetic_entry_for_non_class_singleton` — фикстура
      с `__all__ = ["Widget", "some_singleton"]`, `GET /tools/some_singleton`
      → 200, `{"name": "some_singleton", "module": "__init__", "summary": ""}`
      (зеркало уже существующего `test_list_tools_shows_non_class_singletons_from_dunder_all`,
      но на `GET /tools/{name}`, не `GET /tools`).
- [ ] `get_tool` — если `name` в `public`, но не найдено ни в одном
      `parse_classes(py_file)`, вернуть тот же синтетический словарь, что и
      `list_tools`, вместо падения в `HTTPException(404)`.
- [ ] Regression: существующий `test_get_tool_unknown_404` (имя не в
      `__all__` вообще) остаётся 404 — синтетическая ветка не должна
      маскировать реально несуществующие имена.

---

## Часть 4 — Документация (Н1–Н4 + расширение #6)

Точечные правки, без кода.

- [ ] **Н1** — `docs/agents/api-reference.md`: явно указать, что
      `PUT /connectors/{name}/code` (и аналоги `/actions`, `/workflows/.../code`)
      принимают raw source как тело запроса, не JSON-обёртку.
- [ ] **Н2** — там же (или где описан `GET /workflows/{name}`): поле
      называется `type`, не `workflow_type`, свериться с формулировкой.
- [ ] **Н3** — `docs/compose/plans/2026-07-31-manual-qa-prod-onsite.md` Phase 3.2:
      исправить пример импорта `from soar.tools.http_client import
      http_client_sync` → `from soar.tools import http_client_sync`
      (реально определён в `soar/tools/__init__.py`, не в подмодуле).
- [ ] **Н4** — тот же план, Phase 9: убрать/уточнить формулировку про единый
      `SOAR_WEBHOOK_TOKEN` для всех webhook-воркфлоу — токен per-workflow.
- [ ] **Известное ограничение #6** (`docs/agents/known-limitations.md:12`) —
      дополнить: тот же корень (JWT payload без username) распространяется и
      на `git_author()` (`orchestrator/audit/service.py:12-16`) — git commit
      author для JWT-пользователей подписывается как `user-<id>`, не логином.

---

## Verification

- [ ] `python -m pytest tests/soar/test_runner.py tests/orchestrator/core/test_introspect.py tests/orchestrator/test_subprocess_runner_env.py tests/orchestrator/api/test_tools_api.py -v` — все новые и существующие тесты зелёные
- [ ] `python -m pytest tests/ -q` — без новых регрессий относительно текущего baseline
- [ ] Ручной повтор Phase 5–7 из `docs/compose/plans/2026-07-31-manual-qa-prod-onsite.md`
      на стенде, пересобранном после фикса (см. отчёт §5 — "Если нужна полная
      пересборка образов... весь Phase 0 заново от `python deploy/soarctl install`"):
      воркфлоу `qa_manual_test` с верхнеуровневыми импортами actions
      выполняется успешно. Закрыть три пункта из отчёта §4 ("Что не покрыто"),
      не проверенных в исходной сессии из-за блокера Д1/Д2:
      - [ ] `SOAR_AUDIT_EVENT connector.call`/`connector.call.dry_run`
            появляется в логе джобы (Phase 7.1)
      - [ ] редакция kwargs в `HIDDEN_FIELDS` видна в реальном логе джобы,
            не только в API-ответах (Phase 7.2)
      - [ ] restore workflow-кода (Phase 9.1) реально переисполняется при
            следующем job — не просто читается тот же файл, что и до
            restore (запустить job до restore, поправить код, restore,
            запустить job снова, сравнить наблюдаемое поведение/вывод)
- [ ] Написать отчёт `docs/compose/reports/workflow-connector-scoping.md`
      (Д1+Д2), при необходимости отдельной строкой отметить Д3 и
      документационные правки в том же отчёте или примечанием в
      `known-limitations.md`/`BAGFIX_PLAN.md`, если решено завести туда
      трек — на усмотрение на этапе реализации
