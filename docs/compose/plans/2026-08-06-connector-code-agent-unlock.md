# План: код коннектора агенту, конфиг — человеку

Спека: `docs/compose/specs/2026-08-06-connector-code-agent-unlock-design.md`

Test-first: сначала падающий тест, потом код.

## 1. Тесты (падающие)

- [x] `tests/orchestrator/api/test_agent_role_rbac.py`: перевернуть
      `test_agent_cannot_write_connector_code` → `test_agent_can_write_connector_code`
      (`PUT /connectors/{name}/code` от `agent` → `200`)
- [x] Там же: `403` для `agent` на `GET /{name}/config`,
      `GET /{name}/config/history/{commit}`, `GET /{name}/config/diff`,
      `PUT /{name}/config`, `POST /{name}/config/restore`
- [x] Там же: `200` для `agent` на `GET /{name}/config/history` и `GET /{name}/schema`
- [x] Там же: привести `test_agent_can_restore_connector_code` к версии, где
      откат не сужает `HIDDEN_FIELDS`
- [x] Новый `tests/orchestrator/api/test_connector_hidden_fields_integrity.py`:
      - [x] агент сужает `HIDDEN_FIELDS` через `PUT /code` → `403`, файл на диске не изменился
      - [x] агент расширяет `HIDDEN_FIELDS` → `200`
      - [x] `admin` сужает → `200`
      - [x] регрессия [S1](a): `POST /connectors/x` → admin `PUT /code` с
            `HIDDEN_FIELDS` → агент `restore` на шаблонный коммит → `403`
      - [x] fail-closed: сломанный `.py` → `GET /config` под admin маскирует всё
- [x] Убедиться, что все новые тесты падают по правильной причине

## 2. Код

- [x] `orchestrator/core/introspect.py`: выделить `parse_classes_source(source: str)`,
      `parse_classes(path)` делегирует в неё (без изменения поведения)
- [x] `orchestrator/api/connectors.py`: добавить `_CONFIG_RO`
- [x] `_hidden_fields_for` → `set[str] | None` (`None` при отсутствии файла,
      `SyntaxError`, отсутствии классов)
- [x] `_redact_yaml` / `_redact_diff`: ветка `hidden is None` — маскировать всё
- [x] `save_connector_config`: `if hidden:` → обработка `None`
- [x] Новый `_assert_hidden_fields_not_narrowed(config, name, new_source, user)`
- [x] Роли по таблице [S2](1) спеки: `PUT /code` → `*_ADMIN`; три ручки чтения
      конфига → `*_CONFIG_RO`; `PUT /config` и `POST /config/restore` → `"admin"`
- [x] Проверка сужения в `save_connector_code`, `restore_connector_code`,
      `generate_connector` (для последнего — публичный `OpenAPIGenerator.render_class`)
- [x] Проверить, что `transfer.py` корректно переваривает `None`
- [x] UI зеркалит роли: `ui/src/permissions.js` (+ `connector.config.read`),
      кнопка Setup в `ui/src/views/Connectors.vue`

## 3. Прогон

- [x] `python -m pytest tests/orchestrator/api/test_agent_role_rbac.py tests/orchestrator/api/test_connectors_api.py tests/orchestrator/api/test_connector_hidden_fields_integrity.py -v` — 85 passed
- [x] `python -m pytest tests/ -q` — 831 passed, 3 преэкзистентных Redis-фейла, 9 skipped
- [x] `cd ui && npm test` — 85 passed
- [x] `ruff check` затронутых файлов — новых находок нет

## 4. Документация

- [x] `orchestrator/prompts/system_prompt.md` §4 — переписать блок «One exception»
      (плюс §5/§6/§8, где повторялось старое поведение)
- [x] `docs/agents/security-patterns.md` — абзац D2/B3
- [x] `docs/agents/api-reference.md` — роли затронутых ручек
- [x] `docs/agents/known-limitations.md` — запись из [S3] спеки без смягчения (#9)
- [x] `docs/concepts/BAGFIX_PLAN.md` — отметить, что B3 отменён и почему
- [x] `CHANGELOG.md` (v0.23)
- [x] `docs/compose/reports/connector-code-agent-unlock.md`
- [x] `AGENTS.md` — после выполнения задачи

## 5. Follow-up

- [x] `docs/compose/specs/2026-08-06-connector-secret-runtime-boundary-design.md`
      (спека написана, реализация — отдельный трек)
