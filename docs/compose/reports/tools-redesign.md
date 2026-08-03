# Report: Tools — явный реестр, изоляция внутренностей, HTTP-клиент без async/JSON-only

Spec: `docs/compose/specs/2026-08-03-tools-redesign-design.md`
Plan: `docs/compose/plans/2026-08-03-tools-redesign.md`

## Summary

Реализовано по плану, все 6 шагов. `soar/tools/__init__.py::TOOL_REGISTRY` —
литеральный dict (`kind`: `class`/`instance`/`factory`), единственный источник
для `__all__` и для `GET /tools`; `orchestrator/core/introspect.py::parse_tool_registry`
читает его через AST, `orchestrator/api/tools.py::_resolve` резолвит по `kind`
без синтетической заглушки — нерезолвящееся имя отдаёт `{"error":
"unresolved"}` и пишет `logger.error`. `HttpClient`/`SyncHttpClient` удалены;
`LoggingHttpClient`/`CachingHttpClient` — подклассы `httpx.Client` с
переопределённым `send()`, покрывают любой HTTP-метод и любой тип ответа
(`.json()`/`.content`). `new_client(verify=...)` — для коннекторов с
нестандартным TLS-доверием или персистентным состоянием (cookie jar).
`soar/runner.py` собирает один клиент вместо двух. Внутренняя механика
(`CacheBackend`/`InMemoryCache`/`RedisCache`, SSRF-guard) вынесена в
`soar/tools/_cache.py`/`_net.py`.

Все 10 HTTP-коннекторов `soar-content-pack` мигрированы на `.get()`/`.post()`/
`.put()` + `.json()`/`.content`; `freeipa`/`security_onion` больше не держат
собственный `httpx.Client` — `self._client = new_client(verify=self.verify_ssl)`
в `_connect_impl`, персистентный между вызовами (cookie jar у `freeipa`
работает без ручной пересылки заголовка).

## Отклонение от спека

Версия `soar-content-pack` не поднята — по явному решению пользователя (пак
ещё нигде не установлен, единственный коммит в истории), `manifest.yaml`
перегенерирован с тем же `version: 1.0.0`.

## Побочная находка (вне спека, поправлено по необходимости)

Все 24 `connectors/*/__init__.py` в `soar-content-pack` содержали стале
импорты вида `from soar.connectors.<name>.<name> import ...` — рудимент
до-Phase-3 раскладки (`soar/connectors/` вместо текущего `connectors/`),
ломающий импорт/тесты любого коннектора. Без фикса тесты 10 мигрируемых
коннекторов не собирались бы вообще. Поправлены только 10 файлов, которые
были в скоупе этой задачи (`abusech`, `censys`, `crtsh`, `fofa`, `urlhaus`,
`rstcloud`, `kaspersky_opentip`, `wazuh`, `security_onion`, `freeipa`) —
остальные 14 (`misp`, `mysql`, `shodan`, `smb_rpc`, `winrm` и ещё 9) не
тронуты, у них тот же баг, отдельный трек нужен отдельно.

## Changes

### `soar` repo

- `soar/tools/__init__.py` — `TOOL_REGISTRY` (8 записей) вместо `__all__`-списка
- `soar/tools/_cache.py` (новый) — `CacheBackend`/`InMemoryCache`/`RedisCache`, перенос без изменений
- `soar/tools/_net.py` (новый) — `_is_private_ip`/`_validate_external_url`/`_log_safe_url`, перенос без изменений
- `soar/tools/http_client.py` — переписан: `LoggingHttpClient`/`CachingHttpClient`
  (подклассы `httpx.Client`), `new_client()`, module-level `_shared_cache`/`_shared_default_ttl`/`_shared_domain_ttl`
- `soar/runner.py` — `_build_http_client` строит один клиент и заполняет `_shared_*`; `_build_http_client_sync` удалена
- `soar/audit_hook.py` — обновлена ссылка в докстринге (`HttpClient`/`SyncHttpClient` → `LoggingHttpClient`/`CachingHttpClient`)
- `orchestrator/core/introspect.py` — `parse_tool_registry` вместо `_public_names`
- `orchestrator/api/tools.py` — `_resolve` по `kind`, `list_tools`/`get_tool` переписаны
- Тесты: `tests/soar/tools/test_http_client.py` (переписан), `tests/soar/tools/test_new_client.py` (новый),
  `tests/soar/test_runner.py` (обновлён), `tests/orchestrator/core/test_introspect.py` (добавлены тесты `parse_tool_registry`),
  `tests/orchestrator/api/test_tools_api.py` (переписан под `TOOL_REGISTRY`)

### `soar-content-pack` repo

- 10 коннекторов мигрированы (`abusech`, `censys`, `crtsh`, `fofa`, `urlhaus` —
  простая замена на общий `http_client`; `rstcloud`, `kaspersky_opentip`,
  `wazuh`, `security_onion`, `freeipa` — `new_client(verify=self.verify_ssl)`)
- 10 соответствующих тестов переписаны под новый мок-паттерн (`http_client.get/post` / `new_client()` mock)
- 10 `__init__.py` — исправлен стале импорт (см. побочную находку)
- `manifest.yaml` — перегенерирован (`freeipa`/`security_onion` теряют `httpx` из `imports:`)

## Verification

- [x] `GET /tools` — 8 имён из `TOOL_REGISTRY`, ни одной синтетической заглушки без `error`
- [x] `soar/tools/http_client.py` без `async def`; `HttpClient`/`SyncHttpClient` не существуют (`grep` пуст)
- [x] `_cache.py`/`_net.py` существуют, `http_client.py` их импортирует; их символы не в `TOOL_REGISTRY`
- [x] Ни один файл `soar-content-pack/connectors/` не импортирует `_`-префиксный символ напрямую
- [x] `freeipa.py::_connect_impl`/`security_onion.py::get_pcap` не создают собственный `httpx.Client(...)`
- [x] Все 10 HTTP-коннекторов используют `.get()`/`.post()`/`.put()` + `.json()`/`.content`, `get_json`/`post_json`/`put_json` нигде не встречаются
- [x] `soar`: `pytest tests/ -q` — 812 passed, 9 skipped (3 Redis-integration теста требуют реальный Redis на localhost — не окруженческая регрессия, падают одинаково и на `main` до этой задачи)
- [x] `soar`: `ruff check .` — 0 новых ошибок (38 pre-existing в нетронутых файлах)
- [x] `soar-content-pack`: `pytest tests/ -q --continue-on-collection-errors` — 108 passed, 5 collection errors (все 5 — из побочной находки, вне скоупа этой задачи)
- [x] `soar-content-pack`: `ruff check connectors/ tests/` — 0 ошибок в тронутых файлах (2 pre-existing в `test_mysql_connector.py`, не тронут)
