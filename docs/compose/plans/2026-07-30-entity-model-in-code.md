# Plan: Модель сущностей в коде — Phase 2

Spec: `docs/compose/specs/2026-07-30-entity-model-in-code-design.md`

Ветка: `feat/entity-model-phase2`, из `main` (после мерджа Phase 1 —
зависит от `resolve_content_python`/двух рантаймов, см. spec [S1] п.5 про
`GET /actions`). Мердж в `main` после зелёного `pytest tests/` и
`ruff check .`.

## 1. Реестр коннекторов — пространство имён по типу (E8), spec [S3]

Tests first (`tests/soar/test_connector_registry.py` — найти существующий
файл для `ConnectorRegistry`, дополнить, иначе создать):

- [ ] Два инстанса с одинаковым именем под разными типами — оба
      зарегистрированы, оба доступны через `get_instance(type, name)`
- [ ] Коллизия имени инстанса **внутри одного типа** (два `.yml` одного
      каталога с одинаковым `instances:` ключом, или один файл — дубль
      ключа YAML недопустим, тест собирает через два разных yml-файла в
      одном каталоге типа) — warning в логе, last-wins, не исключение
- [ ] `_discover_classes`: файл коннектора, импортирующий класс другого
      коннектора (`from soar.connectors.other_type.other import
      OtherConnector` на top-level) — не перезаписывает `_classes[this_type]`
      чужим классом (regression на E8 "смежное")
- [ ] `list()` — форма ответа не меняется (`[{"name", "type", "connected"}]`),
      расплющивает вложенную структуру
- [ ] Confirm collision-warning test fails against current implementation
      first (baseline)

Implementation — `soar/connectors/__init__.py`:

- [ ] `_connectors`/`_configs` → `dict[str, dict[str, ...]]` (type →
      instance), как в spec [S3]
- [ ] `_discover_classes`/`_discover_external`: добавить
      `and obj.__module__ == fqn` в условие
- [ ] `_load_configs_from_dir`: bucket по `type_name`, warning на дубль
      ключа внутри bucket
- [ ] `init()`: строит `self._connectors[type][instance]`
- [ ] `list()`: расплющивает вложенную структуру, форма не меняется
- [ ] Новый метод `get_instance(type_name, instance_name) -> BaseConnector | None`
- [ ] Удалить `soar/connectors/es_http/` (пустой каталог)

## 2. Ленивые шимы + прокси (E6+E3), spec [S4]

Tests first (`tests/soar/test_connector_proxy.py`, `tests/soar/test_runtime_state.py`):

- [ ] `soar/runtime_state.py`: `set_dry_run`/`is_dry_run` round-trip
- [ ] `ConnectorProxy(instance, type_name).some_public_method(...)` —
      вызывает `instance.some_public_method`, возвращает то же значение
- [ ] Приватный атрибут (`_foo`)/не-callable — отдаётся как есть, без
      обёртки/лога
- [ ] Вызов публичного метода пишет одну лог-строку с
      `SOAR_AUDIT_EVENT connector.call target=<type>.<instance>.<method>`,
      `duration_ms=`, `outcome=ok`
- [ ] `kwargs`, ключи которых в `HIDDEN_FIELDS` инстанса — в логе `***`;
      реальный вызов метода получает исходное значение (mock метод,
      проверить `call_args`)
- [ ] Метод в `MUTATING_METHODS` + `is_dry_run() is True` — метод не
      вызывается (mock `assert_not_called`), возврат `None`, лог содержит
      `connector.call.dry_run`
- [ ] Метод в `MUTATING_METHODS` + `is_dry_run() is False` — вызывается
      нормально
- [ ] Метод кидает `ValueError` — лог `outcome=error:ValueError`,
      `ValueError` пробрасывается из `wrapper(...)`
- [ ] Confirm tests fail before `ConnectorProxy` exists

Tests first (`tests/soar/test_connectors_init.py`):

- [ ] Built-in `file` коннектор (не требует внешних кредов) с тестовым
      конфигом → `from soar.connectors.file import <instance>` возвращает
      `ConnectorProxy`
- [ ] Опечатка в имени инстанса → `AttributeError` при доступе к атрибуту
      модуля (симулирует `from ... import typo` через `getattr(sys.modules[fqn], "typo")`)
- [ ] `connectors.<instance>` (плоский путь через `ConnectorRegistry.__getattr__`)
      тоже возвращает `ConnectorProxy`, не сырой инстанс
- [ ] Confirm tests fail before shim wiring exists

Implementation:

- [ ] `soar/runtime_state.py` — как в spec [S4]
- [ ] `soar/connectors/_proxy.py` — `ConnectorProxy` как в spec [S4]
- [ ] `soar/connectors/base.py`: `MUTATING_METHODS: ClassVar[set[str]] = set()`
      на `BaseConnector`
- [ ] `soar/connectors/__init__.py`: `_install_shims()`, вызов из `init()`
      после construction; `ConnectorRegistry.__getattr__` возвращает
      `ConnectorProxy` (не `self._connectors[name]` напрямую)
- [ ] `soar/runner.py::main()`: `set_dry_run(bool(context.get("dry_run",
      False)))` после парсинга `context`, до `workflows.execute(...)`
- [ ] Пройтись по всем 24 коннекторам (`soar/connectors/*/*.py`) —
      проставить `MUTATING_METHODS` на реально мутирующих методах (список
      per-коннектор — составить при реализации, ориентируясь на
      docstring/названия методов; read-only geт/search/list/query — не
      входят)
- [ ] `orchestrator/api/workflows.py::TEMPLATES` (`SCHEDULED_TEMPLATE`,
      `WEBHOOK_TEMPLATE`, `MANUAL_TEMPLATE`) — заменить
      `from soar.connectors import connectors` +
      `connectors.<name>....` на пример
      `from soar.connectors.<type> import <instance>` (текстовый плейсхолдер
      + комментарий, без реальной привязки к настроенному типу)
- [ ] `orchestrator/api/actions.py::ACTION_TEMPLATE` — то же самое

## 3. Аудит вызовов из джобы → `AuditLog`, spec [S6]

Tests first (`tests/orchestrator/core/test_audit_parse.py`):

- [ ] Парсер на строку `... SOAR_AUDIT_EVENT connector.call target=virus_total.vt_main.get_ip_report args=('1.2.3.4',) kwargs={} duration_ms=120 outcome=ok job_id=abc123` →
      структура `{"target": "virus_total.vt_main.get_ip_report", "dry_run":
      False, "duration_ms": 120, "outcome": "ok", "job_id": "abc123"}`
- [ ] `connector.call.dry_run` вариант → `"dry_run": True`, `duration_ms`
      может отсутствовать
- [ ] `outcome=error:ValueError` — распознаётся как non-ok outcome
- [ ] Строка без префикса `SOAR_AUDIT_EVENT` — игнорируется (не кидает)
- [ ] Пустой/битый job.log — пустой список событий, не исключение
- [ ] Confirm tests fail before parser exists — зафиксировать точный regex
      при реализации (совместно с форматом строки из раздела 2)

Tests first (`tests/orchestrator/test_worker_audit_events.py`):

- [ ] `Worker._execute` с job.log, содержащим 2 `SOAR_AUDIT_EVENT` строки
      + финальную JSON-строку результата → 2 вызова
      `audit_service.record_job_event` (мокнуть), с правильным
      `resource_id`/`detail`
- [ ] job.log без audit-строк → `record_job_event` не вызывается
- [ ] `db_session_factory=None` (обратная совместимость конструктора) →
      парсинг событий пропускается целиком, не падает
- [ ] Confirm tests fail before wiring exists

Implementation:

- [ ] `orchestrator/core/audit_parse.py` — regex/парсер, как в spec [S6]
      (зафиксировать точный формат вместе с [S4]/proxy — один PR правит
      оба конца)
- [ ] `orchestrator/audit/service.py`: `record_job_event(db, *, job,
      action, resource_id, detail)` — синтетический actor
      `actor_type="service"`, `actor_name=f"job:{job.workflow_name}"`
- [ ] `orchestrator/core/worker.py::Worker.__init__`: новый опциональный
      параметр `db_session_factory=None`
- [ ] `Worker._execute`: после существующего блока чтения `lines` —
      если `db_session_factory` задан, распарсить audit-события,
      создать сессию, вызвать `record_job_event` на каждое; обернуть в
      try/except, чтобы сбой парсинга/записи аудита не переводил джобу в
      FAILED (аудит — наблюдаемость, не должен ронять исполнение)
- [ ] `orchestrator/core/worker_pool.py` (или где сегодня инстанцируется
      `Worker`) — прокинуть `app.state.db_session_factory`

## 4. Экшены: несколько экспортов (E7), spec [S7]

Tests first (`tests/soar/test_actions_registry.py`):

- [ ] Файл с двумя public функциями (`enrich_ip`, `enrich_domain`) — обе
      зарегистрированы под своими именами
- [ ] Приватная функция (`_helper`) — не регистрируется
- [ ] Функция, импортированная из другого модуля на top-level (например
      `from os.path import join` внутри тестового action-файла) — не
      регистрируется (`__module__ != fqn`)
- [ ] Коллизия имени между двумя файлами — warning + last-wins
- [ ] Confirm tests fail against current (имя-файла-only) implementation

Tests first (`tests/orchestrator/api/test_actions_routes.py`):

- [ ] `GET /actions` на каталог с файлом из 2 public функций → 2 записи в
      ответе (сегодня — 0, т.к. ни одна не совпадает с именем файла, если
      имя файла не равно ни одной из функций — использовать этот кейс как
      regression)
- [ ] `GET /actions` не импортирует файлы из `actions_dir` (patch
      `importlib.import_module`/`importlib.util.spec_from_file_location`,
      `assert_not_called`)
- [ ] Confirm tests fail before change

Implementation:

- [ ] `soar/actions/__init__.py::_discover`/`_discover_external` — как в
      spec [S7], регистрация по имени callable + `__module__ == fqn`
- [ ] `orchestrator/api/actions.py::list_actions` — AST-путь
      (`parse_functions` на все public top-level функции файла), без
      импорта, как в spec [S7]
- [ ] `_describe_action_summary` — либо инлайнится в новый `list_actions`,
      либо остаётся отдельной функцией, вызываемой на найденную `fn`, а не
      повторно ищущей по имени файла (убрать дублирование парсинга файла
      дважды на один и тот же путь)

## 5. Явная поверхность инструментов (E5), spec [S8]

Tests first (`tests/orchestrator/api/test_tools_routes.py`):

- [ ] `GET /tools` не содержит `CacheBackend`/`InMemoryCache`/`RedisCache`/
      `OpenAPIGenerator`
- [ ] `GET /tools` содержит `http_client`/`http_client_sync` (без класса,
      `module: "__init__"`)
- [ ] `GET /tools` содержит `WatermarkStore`/`SeenStore`
- [ ] Confirm tests fail against current glob-based implementation (сегодня
      показывает все 8 классов)

Tests first (`tests/soar/tools/test_watermark.py`):

- [ ] `watermark_store("my_workflow")` — путь вычисляется из конфига +
      имени, не требует ручной передачи пути
- [ ] `seen_store("my_workflow", ttl=3600)` — то же самое
- [ ] Прямое инстанцирование `WatermarkStore(path=...)` — не ломается
      (классы остаются публичными)
- [ ] Confirm tests fail before factories exist

Implementation:

- [ ] `orchestrator/core/openapi_generator.py` — переезд содержимого
      `soar/tools/openapi.py` без изменения поведения; обновить импорт в
      `orchestrator/api/connectors.py:366`
- [ ] Удалить `soar/tools/openapi.py`
- [ ] `soar/tools/watermark.py`: добавить `watermark_store(name)`/
      `seen_store(name, ttl=86400)` — путь строится из конфига (найти
      подходящее поле на этапе реализации — вероятно новый
      `SoarConfig.state_dir` рядом с `workflows_dir`/`connectors_dir`/
      `actions_dir` в `orchestrator/config.py`, дефолт
      `/app/data/state`); фабрики читают путь через `SOAR_CONFIG`-подобный
      механизм, симметричный тому, как `soar/runner.py` уже читает
      `config.yaml` (не заводить второй способ чтения конфига в `soar/`)
- [ ] `soar/tools/__init__.py`: `__all__ = ["http_client", "http_client_sync",
      "WatermarkStore", "SeenStore", "watermark_store", "seen_store"]`
- [ ] `orchestrator/core/introspect.py`: `_public_names(init_path)` — AST
      парсер `__all__`, как в spec [S8]
- [ ] `orchestrator/api/tools.py::list_tools`/`get_tool` — фильтрация по
      `_public_names` + отдельная ветка для синглтонов-не-классов

## 6. Миграция оставшихся 7 коннекторов на `http_client_sync`, spec [S9]

По одному, тем же паттерном, что `abusech`/`rstcloud`/`kaspersky_opentip`
(`docs/compose/plans/2026-07-28-http-client-sync-facade.md`, разделы
"Implementation — connector migration" и "Tests — connector migration" —
использовать как чек-лист-шаблон на каждый из 7):

- [ ] `censys` + `tests/soar/test_censys_connector.py`
- [ ] `crtsh` + `tests/soar/test_crtsh_connector.py`
- [ ] `fofa` + `tests/soar/test_fofa_connector.py`
- [ ] `freeipa` + `tests/soar/test_freeipa_connector.py`
- [ ] `security_onion` + `tests/soar/test_security_onion_connector.py`
- [ ] `urlhaus` + `tests/soar/test_urlhaus_connector.py`
- [ ] `wazuh` + `tests/soar/test_wazuh_connector.py`

## 7. Docs

- [ ] `docs/agents/known-limitations.md` — переформулировать пункт 9 (E1)
      под текущее состояние (структурный дубль по-прежнему существует до
      Фазы 3, но логирование/dry-run/аудит теперь гарантированы вне
      зависимости от источника)
- [ ] `AGENTS.md` — обновить примеры импорта коннектора в разделе "Key
      patterns"/"File map" на концептную форму; упомянуть
      `ConnectorProxy`/`MUTATING_METHODS`/`SOAR_AUDIT_EVENT` там, где
      сегодня описан `_ensure_connected`/`HIDDEN_FIELDS`

## Verification

- [ ] `python -m pytest tests/soar/test_connector_registry.py
      tests/soar/test_connector_proxy.py tests/soar/test_runtime_state.py
      tests/soar/test_connectors_init.py tests/orchestrator/core/test_audit_parse.py
      tests/orchestrator/test_worker_audit_events.py tests/soar/test_actions_registry.py
      tests/orchestrator/api/test_actions_routes.py tests/orchestrator/api/test_tools_routes.py
      tests/soar/tools/test_watermark.py -v`
- [ ] Полный `python -m pytest tests/soar/test_*_connector.py -v` (все 24)
- [ ] `python -m pytest tests/ -q` — ноль новых failures относительно
      baseline после Phase 1
- [ ] `ruff check .`
- [ ] Написать отчёт `docs/compose/reports/entity-model-in-code.md`
