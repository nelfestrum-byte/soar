# Report: код коннектора агенту, значения конфига человеку

Spec: `docs/compose/specs/2026-08-06-connector-code-agent-unlock-design.md`
Plan: `docs/compose/plans/2026-08-06-connector-code-agent-unlock.md`

## Summary

Повод — фидбэк из боя: агент создал коннектор `elastic_trueconf`, написал
код и получил `403` на `PUT /connectors/elastic_trueconf/code` (поведение
B3). Механизма «агент предлагает — человек утверждает» в API нет, поэтому
оператору оставалось руками переносить многострочный Python через Swagger UI.

При разборе выяснилось, что барьер B3 не выполнял свою функцию.
`POST /connectors/{name}` разрешён роли `agent` и коммитит
`CONNECTOR_TEMPLATE` с пустым `HIDDEN_FIELDS`; `POST /{name}/code/restore`
оставался на `_ADMIN`. Агент откатывался на собственный шаблонный коммит и
снимал редакцию, не вызывая `PUT`. Посылка B3 («любая версия в истории
писалась `admin`-ом») не учитывала коммит от `POST`. Ограничение при этом
било по основному сценарию роли.

Дополнительно `_hidden_fields_for` работал fail-open: отсутствие `.py`,
`SyntaxError` или отсутствие классов давали пустое множество, неотличимое
от «секретов нет», и `GET /config` отдавал файл без маскировки.

## Changes

### Роли (`orchestrator/api/connectors.py`)

- Новый `_CONFIG_RO = ("viewer", "analyst", "service", "admin")` — `_RO` без `agent`.
- `PUT /{name}/code`: литеральный `"admin"` → `*_ADMIN`.
- `GET /{name}/config`, `/config/history/{commit}`, `/config/diff`: `*_RO` → `*_CONFIG_RO`.
- `PUT /{name}/config`, `POST /{name}/config/restore`: `*_ADMIN` → литеральный `"admin"`.
- Без изменений: `GET /{name}/config/history` (список коммитов, без значений)
  и `GET /{name}/schema` — оба остаются на `_RO` и составляют штатную
  поверхность агента для конфигурирования коннектора.

Запись конфига забрана вместе с чтением осознанно: `PUT` пишет файл целиком,
слепая запись затирала бы значения, которых пишущий не видит.

### Редакция fails closed

- `_hidden_fields_for` → `set[str] | None`; `None` = политика не читается.
  Пустое множество сохраняет прежний смысл «секретов нет» — это то, что
  явно объявляет `CONNECTOR_TEMPLATE`.
- `_redact_yaml`/`_redact_diff` при `None` маскируют все значения под
  `instances.*` / все строки `key: value`.
- `save_connector_config`: `if hidden:` → `if hidden is None or hidden:`;
  `_merge_hidden_fields` при `None` итерирует по фактическим ключам инстанса.
- `orchestrator/api/transfer.py` получает то же поведение через общие
  функции — экспорт нечитаемого коннектора тоже маскируется целиком.

### Монотонность `HIDDEN_FIELDS`

- `orchestrator/core/introspect.py`: `parse_classes_source(source)` выделен,
  `parse_classes(path)` делегирует в неё — нужен разбор ещё не записанного текста.
- `orchestrator/core/openapi_generator.py`: публичный `render_class(name)` —
  чтобы роут проверял будущий код, не трогая приватный `_generate_class`.
- Новый `_assert_hidden_fields_not_narrowed(config, name, new_source, user)`:
  `admin` пропускается; иначе требуется `new >= old`, а `None` с любой
  стороны (кроме случая «файла ещё нет») → `403`.
- Вызывается во всех трёх путях записи кода: `PUT /code` (после
  `validate_connector_code`, до записи), `POST /code/restore` (содержимое
  целевого коммита через `history.get_version` — до отката) и
  `POST /generate` (перезапись существующего коннектора). Полнота покрытия
  здесь и есть урок B3.

### UI

- `ui/src/permissions.js`: `connector.code.write` → `['admin', 'agent']`,
  `connector.config.write` → `['admin']`, новая `connector.config.read`.
- `ui/src/views/Connectors.vue`: кнопка **Setup** скрыта для ролей без
  права читать конфиг — иначе она вела бы в гарантированный `403`.

### Документация

`orchestrator/prompts/system_prompt.md` (§4 переписан, §5/§6/§8 приведены в
соответствие), `docs/agents/security-patterns.md`, `docs/agents/api-reference.md`,
`docs/agents/known-limitations.md` (новый #9), `docs/concepts/BAGFIX_PLAN.md`
(B3 помечен как перезакрытый, с разбором почему первое закрытие было неполным),
`CHANGELOG.md` (v0.23).

## Testing

```
python -m pytest tests/orchestrator/api/test_connector_hidden_fields_integrity.py \
                 tests/orchestrator/api/test_agent_role_rbac.py \
                 tests/orchestrator/api/test_connectors_api.py -q
85 passed

python -m pytest tests/ -q
831 passed, 3 failed, 9 skipped
```

Три падения — `tests/orchestrator/test_redis_integration.py`, требуют живой
Redis на `localhost:6379` (`ConnectionError` на `asyncio.open_connection`),
к правке отношения не имеют.

```
cd ui && npm test
16 files, 85 passed
```

Новый `tests/orchestrator/api/test_connector_hidden_fields_integrity.py`:
сужение через `PUT` (403 + файл на диске не изменился), расширение агентом
(200), сужение админом (200), обход `POST /connectors` → admin `PUT` →
агентский `restore` на шаблонный коммит (403, и последующий `GET /config`
под admin по-прежнему маскирует), admin-restore на тот же коммит (200),
fail-closed при сломанном и при удалённом `.py`.

В `test_connectors_api.py` два теста поменяли смысл вместе с поведением:
`test_agent_forbidden_from_connector_code_write` →
`test_agent_can_write_connector_code_keeping_hidden_fields`, и
`test_put_config_agent_can_change_non_hidden_field` →
`..._cannot_...` (теперь `403` на уровне роута, а не поля).

## Success criteria (spec S5)

- [x] `PUT /connectors/{name}/code` от роли `agent` — `200`; сценарий из
      фидбэка проходит без admin-ключа
- [x] `agent` получает `403` на чтение и запись конфига; `schema` и список
      коммитов конфига остаются
- [x] `HIDDEN_FIELDS` невозможно сузить ролью `agent` ни через `PUT /code`,
      ни через `restore`, ни через `generate`
- [x] Нечитаемый/отсутствующий `.py` больше не даёт конфиг без маскировки —
      ни в `GET /config`, ни в `/config/diff`, ни в `/transfer/export`
- [x] Документация обновлена; `known-limitations.md` #9 содержит запись из
      [S3] без смягчения

## Что осталось открытым (сознательно)

Роль `agent` по-прежнему получает credential в рантайме: у неё есть
произвольное исполнение кода (`PUT /workflows/{name}/code` + `POST /jobs`),
креды монтируются в субпроцесс открытым YAML, `ConnectorProxy.__getattr__`
отдаёт `conn.api_key` и `conn._instance` сырыми, логи джоба не редактируются.
`print(conn.api_key)` + `GET /logs/{id}` работает и до, и после этого трека.

Это записано в Known Limitations #9 и разобрано в
`docs/compose/specs/2026-08-06-connector-secret-runtime-boundary-design.md`
(спека написана, реализация — отдельный трек). Формулировку не смягчать:
сделанное здесь — целостность политики редакции и гигиена API-поверхности,
а не граница безопасности против враждебного агента.
