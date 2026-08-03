# Plan: Tools — явный реестр, изоляция внутренностей, HTTP-клиент без async/JSON-only

Spec: `docs/compose/specs/2026-08-03-tools-redesign-design.md` (отменяет
`2026-07-31-tools-singleton-introspection-design.md`, Д4).

Ветка: `feat/tools-redesign`, из `main`. Два репозитория в рамках одной
задачи: `soar` (этот) и `../soar-content-pack` (локальный, без remote,
без своего spec-процесса — правки идут в рамках этого же трека, отдельным
коммитом/коммитами в его собственной git-истории). Мердж `soar` после
зелёного `pytest tests/` и `ruff check .`; `soar-content-pack` — после
зелёного `pytest` внутри него.

Порядок шагов важен: 1→2 меняют форму реестра и интроспекции (не трогая
`http_client.py` изнутри), 3 переписывает сам HTTP-клиент, 4 — сборку в
`runner.py`, 5 — миграцию контентпака (зависит от 3+4 — новый API клиента
должен уже существовать). Каждый шаг оставляет `soar`-репозиторий в
зелёном состоянии, чтобы `soar-content-pack` можно было мигрировать в
конце, один раз, без промежуточных half-migrated состояний.

## 1. `TOOL_REGISTRY` + `parse_tool_registry` + резолв по `kind`

Tests first (`tests/orchestrator/test_introspect.py`, новый файл —
`orchestrator/core/introspect.py` сегодня не имеет отдельного файла тестов
для функций, кроме тех, что дублируются в `test_tools_api.py`; создать):

- [ ] `parse_tool_registry(init_path)` на синтетическом `__init__.py` с
      `TOOL_REGISTRY = {...}` — возвращает dict как есть (`ast.literal_eval`)
- [ ] `parse_tool_registry` на файле без `TOOL_REGISTRY` — возвращает `{}`
- [ ] Confirm: тест падает (функции не существует) до реализации

Tests first (`tests/orchestrator/api/test_tools_api.py` — переписывается
почти полностью, см. [S3] спека; фикстуры строят `TOOL_REGISTRY`, не
`__all__`):

- [ ] `_write_init(tmp_path, registry: dict)` — новый хелпер, пишет
      `TOOL_REGISTRY = {...!r}` + `__all__ = list(TOOL_REGISTRY)`
- [ ] `GET /tools` c `kind="class"` — карточка как сегодня (docstring/
      constructor/methods), без изменений формы
- [ ] `GET /tools` c `kind="instance"` (`of: "Widget"`) — карточка класса
      `Widget`, но `name` — публичное имя инстанса, плюс поле
      `instance_of == "Widget"`
- [ ] `GET /tools` c `kind="factory"` — `{"name", "module", "kind":
      "function", "signature", "docstring"}` (форма как у
      `parse_functions`, не синтетическая заглушка)
- [ ] `GET /tools` — имя в реестре, но модуль/класс не резолвится (битый
      `module` или `of`) → `{"name", "module", "summary": "", "error":
      "unresolved"}`, **не** тихая заглушка без пометки — регресс-тест на
      то, что задача [S2](a) фиксирует явно (сегодняшний код молча отдаёт
      `{"summary": ""}` без `error`)
- [ ] `GET /tools/{name}` — тот же резолв для одного имени, 404 если имени
      нет в `TOOL_REGISTRY` вообще (не "нет в `__all__`")
- [ ] Удалить тесты, привязанные к старой форме: `test_list_tools_filters_by_dunder_all`
      (переписать под `TOOL_REGISTRY`), `test_get_tool_returns_synthetic_entry_for_non_class_singleton`
      и `test_list_tools_shows_non_class_singletons_from_dunder_all` (заменяются
      тестами на `kind="instance"`/`kind="factory"` выше — синтетической
      заглушки без `error` больше не существует)
- [ ] `test_real_soar_tools_dunder_all_excludes_internals` — обновить под
      реальный `soar/tools/__init__.py::TOOL_REGISTRY` после шага 2 (8 имён
      из спека [S2](a): `http_client`, `LoggingHttpClient`,
      `CachingHttpClient`, `new_client`, `WatermarkStore`, `SeenStore`,
      `watermark_store`, `seen_store`); `CacheBackend`/`InMemoryCache`/
      `RedisCache`/`_validate_external_url` по-прежнему отсутствуют
- [ ] Confirm: все новые/переписанные тесты падают до реализации (старая
      `list_tools`/`get_tool` не знают про `TOOL_REGISTRY`)

Implementation:

- [ ] `orchestrator/core/introspect.py` — добавить `parse_tool_registry`
      (как в спеке [S2](a)); `_public_names` можно оставить (не мешает,
      но больше не используется в `tools.py` — если ничего другого её не
      зовёт, удалить вместе с её собственными тестами, проверить `grep -rn
      "_public_names"` перед удалением)
- [ ] `orchestrator/api/tools.py` — заменить `list_tools`/`get_tool` на
      версию из спека: `parse_tool_registry` + `_resolve(tools_dir, name,
      meta)` по `kind`, без ветки `class_names = ... for name in sorted(public
      - class_names)`; `_resolve` возвращает `{"error": "unresolved"}` на
      нерезолвящееся имя, залогировать через `orchestrator`'s стандартный
      логгер (посмотреть, как логируют другие роуты `orchestrator/api/`,
      использовать тот же паттерн) — конфигурационная ошибка, не тихая UI-заглушка
- [ ] Убедиться, что `Depends(require_role(*_RO))` и `HTTPException(404, ...)`
      сохраняются на обоих роутах (не задеты рефактором резолва)

## 2. `soar/tools/__init__.py` → `TOOL_REGISTRY` + внутренние `_*.py`

Не отдельные тесты (реализация регистра из спека, покрывается тестами шага
1 и шага 3) — переносится вместе:

- [ ] `soar/tools/_cache.py` (новый) — `CacheBackend`, `InMemoryCache`,
      `RedisCache` из `http_client.py`, без изменений в реализации
- [ ] `soar/tools/_net.py` (новый) — `_is_private_ip`, `_validate_external_url`,
      `_log_safe_url` из `http_client.py`, без изменений в реализации
- [ ] `soar/tools/__init__.py` — literal `TOOL_REGISTRY` как в спеке
      [S2](a) (8 записей); `__all__ = list(TOOL_REGISTRY)`; убрать старые
      docstring-комментарии про AST-эвристику (`_public_names`), заменить
      комментарием про `TOOL_REGISTRY` как единственный источник для
      `__all__` и `GET /tools`
- [ ] `grep -rn "from soar.tools.http_client import.*Cache\|from soar.tools.http_client import _"`
      по `soar/` и `../soar-content-pack/` — обновить любые прямые импорты
      `CacheBackend`/`InMemoryCache`/`RedisCache` на `soar.tools._cache`
      (`soar/runner.py` — единственный ожидаемый потребитель, см. шаг 4)

## 3. `LoggingHttpClient`/`CachingHttpClient` — подкласс `httpx.Client`

Tests first — `tests/soar/tools/test_http_client.py` переписывается
полностью (не патчится), мокает `httpx.Client.send`, не
`httpx.Client()`/`httpx.AsyncClient()` как контекст-менеджер:

- [ ] `LoggingHttpClient().get(url)` — один INFO-лог на запрос (успех),
      `send()` реально вызывает `super().send()` (проверить через patch
      `httpx.Client.send`)
- [ ] Ошибочный статус (4xx/5xx) — лог всё равно пишется **до**
      `raise_for_status()` (проверить порядок: patch `_log.info` и
      `raise_for_status` side_effect, assert call order через `Mock`
      `call_args_list`/`mock.mock_calls` на общем `Mock` с обоими
      прикреплёнными атрибутами, или проще: assert INFO-лог записан, затем
      assert `HTTPStatusError` поднялся)
- [ ] SSRF-guard: приватный IP → `ValueError` **до** реального сетевого
      вызова (`_validate_external_url` вызывается первым в `send()`,
      `super().send()` не вызван — patch и assert `not_called()`)
- [ ] `follow_redirects=False` и `timeout=30` — дефолты конструктора,
      проверить через `httpx.Client.__init__` или через публичные атрибуты
      клиента (`client.follow_redirects`, `client.timeout`)
- [ ] `verify=False` передаётся в `super().__init__` и держится на
      инстансе (не per-call параметр) — `LoggingHttpClient(verify=False)`,
      проверить `client._transport`/официальный публичный способ проверки
      httpx verify (смотреть, что доступно в установленной версии httpx)
- [ ] `CachingHttpClient` без `cache=` — ведёт себя как `LoggingHttpClient`
      (GET не кэшируется, если `_cache is None`)
- [ ] `CachingHttpClient` с кэшем — второй `GET` того же URL не долетает
      до `super().send()` (mock `httpx.Client.send`, assert
      `call_count == 1` после двух `.get(url)`)
- [ ] Кэш наполняется только на успешный ответ — mock `send` бросает
      `HTTPStatusError` (через реальный `raise_for_status` на
      `httpx.Response` с 500) → `cache.set` не вызван
- [ ] `POST`/`PUT`/`DELETE` никогда не кэшируются, даже с `cache=` заданным
      (два одинаковых `POST` → `super().send()` вызван дважды)
- [ ] Confirm: все тесты падают до реализации (`LoggingHttpClient`/
      `CachingHttpClient` не существуют)

Implementation:

- [ ] `soar/tools/http_client.py` — удалить `HttpClient`, `SyncHttpClient`,
      `_key`/`_ttl_for` bound methods; оставить/перенести module-level
      `_cache_key`, `_ttl_for` (уже module-level в текущем коде — не
      трогать); импортировать `CacheBackend` из `._cache`,
      `_validate_external_url`/`_log_safe_url` из `._net`
- [ ] `LoggingHttpClient(httpx.Client)` — `__init__`/`send()` как в спеке
      [S2](c), докстринг про "не JSON-специфичен" оставить (WHY уже
      написан в спеке, перенести as-is)
- [ ] `CachingHttpClient(LoggingHttpClient)` — `__init__`/`send()` как в
      спеке [S2](c)
- [ ] Убрать старый модульный докстринг верхнего уровня файла, если он
      ссылается на удалённые `HttpClient`/`SyncHttpClient` — актуализировать
      под новые два класса, сохранить WHY про `_validate_external_url`
      reimplementation (граница `soar/`↔`orchestrator/` не изменилась)

## 4. `new_client()` + `soar/runner.py` — одна сборка вместо двух

Tests first (`tests/soar/tools/test_new_client.py`, новый):

- [ ] До вызова `runner.py`-инициализации (`_shared_cache is None` в
      исходном состоянии модуля) — `new_client()` возвращает
      `LoggingHttpClient` без кэша
- [ ] После `_build_http_client(config)` (эмулировать: присвоить
      `http_client._shared_cache`/`_shared_default_ttl`/`_shared_domain_ttl`
      вручную в тесте, как это делает `runner.py`) — `new_client()`
      возвращает `CachingHttpClient` с тем же объектом `_shared_cache`
      (`is`, не `==`)
- [ ] `new_client(verify=False)` — `verify=False` доезжает до
      `httpx.Client.__init__` независимо от `_shared_cache`
      (проверить и ветку с кэшем, и без)
- [ ] Confirm: падают до реализации (`new_client` не существует)

Tests first (`tests/soar/test_runner.py` — обновить существующие, не
только добавить):

- [ ] `test_build_http_client_defaults_to_memory_cache` и соседние 4 теста
      (`..._none_backend_has_no_cache`, `..._reads_ttl_and_domain_ttl`,
      `..._redis_backend_uses_queue_redis_url`, `..._unknown_backend_raises`)
      — обновить импорт/тип ожидаемого результата на
      `CachingHttpClient`/`LoggingHttpClient` вместо `HttpClient`, поведение
      не меняется
- [ ] Удалить `test_build_http_client_sync_shares_cache_with_async_client`
      целиком — `_build_http_client_sync` больше не существует, эту
      гарантию теперь покрывает `test_new_client.py` выше (общий
      `_shared_cache` между синглтоном и `new_client()`)
- [ ] `test_runner_assigns_http_client_before_registry_init` — обновить
      строку, которую он ищет в исходнике (`tools.http_client =
      _build_http_client(config)` остаётся, но исчезает вторая строка про
      `http_client_sync`) — проверить, что тест по-прежнему падает
      корректно, если строку убрать целиком (переписать assertion)
- [ ] `test_from_import_http_client_sees_configured_instance_when_assigned_before_init`
      и `..._captures_stale_default_when_assigned_after_init` — не
      завязаны на `HttpClient` конкретно, скорее всего не требуют правок,
      проверить импорт в начале файла (`from soar.tools.http_client import
      InMemoryCache, RedisCache` — эти два класса переехали в `_cache.py`,
      обновить импорт)
- [ ] Confirm: падают до реализации (после удаления `_build_http_client_sync`
      из `runner.py`, но до обновления тестов)

Implementation:

- [ ] `soar/tools/http_client.py` — добавить `_shared_cache`/
      `_shared_default_ttl`/`_shared_domain_ttl` module-level + `new_client(verify=True)`
      как в спеке [S2](d)
- [ ] `soar/runner.py` — `_build_http_client(config)` возвращает
      `LoggingHttpClient`/`CachingHttpClient` (не `HttpClient`), заполняет
      `http_client._shared_cache` и парные поля **до** `return` (см. спек
      [S2](e) — порядок важен, `new_client()` вызванный из
      `_connect_impl` любого коннектора должен видеть уже заполненные
      значения)
- [ ] Удалить `_build_http_client_sync` целиком
- [ ] `tools.http_client = _build_http_client(config)` остаётся; удалить
      строку `tools.http_client_sync = _build_http_client_sync(...)`
- [ ] Импорт в шапке `runner.py`: `from soar.tools.http_client import
      LoggingHttpClient, CachingHttpClient, new_client` + `from
      soar.tools._cache import CacheBackend, InMemoryCache, RedisCache`
      (место `HttpClient, InMemoryCache, RedisCache, SyncHttpClient`)

## 5. Миграция `soar-content-pack` (отдельный репозиторий)

Зависит от шагов 3+4 (нужен реальный `new_client()`/`.get()`/`.post()` API
на диске). Выполняется одним проходом по всем 10 файлам — тесты внутри
`soar-content-pack/tests/` переписываются вместе с каждым коннектором, не
двумя раздельными коммитами (иначе промежуточное состояние красное).

### 5.1 Простая замена (общий синглтон `http_client`)

Файлы: `abusech/abusech.py`, `censys/censys.py`, `crtsh/crtsh.py`,
`fofa/fofa.py`, `urlhaus/urlhaus.py`.

- [ ] Импорт: `from soar.tools import http_client_sync` →
      `from soar.tools import http_client`
- [ ] `http_client_sync.get_json(url, headers=h)` →
      `http_client.get(url, headers=h).json()`
- [ ] `http_client_sync.post_json(url, data, headers=h)` →
      `http_client.post(url, json=data, headers=h).json()`
- [ ] `_connect_impl` остаётся `pass` (комментарий "http_client_sync opens
      a connection per request..." теперь неверен — `LoggingHttpClient` не
      открывает соединение per-request, это persistent `httpx.Client`;
      обновить комментарий или убрать — соединение всё равно лениво
      открывается httpx, `_connect_impl` как no-op остаётся корректным
      просто по другой причине: коннектор не держит собственного клиента)
- [ ] Соответствующие тесты (`tests/test_abusech_connector.py`,
      `test_censys_connector.py`, `test_crtsh_connector.py`,
      `test_fofa_connector.py`, `test_urlhaus_connector.py`) — мокать
      `soar.tools.http_client.get`/`.post` (модульный синглтон,
      `LoggingHttpClient` instance) вместо `.get_json`/`.post_json`;
      patch `httpx.Client.send` на объекте синглтона либо patch метод
      `.get`/`.post` напрямую — решить по месту, глядя на существующий
      паттерн мокания в каждом файле
- [ ] Confirm: тесты падают сразу после смены импорта/вызовов, до правки
      тестов — затем зелёные после правки тестов

### 5.2 Свой инстанс (`new_client(verify=self.verify_ssl)`)

Файлы: `rstcloud/rstcloud.py`, `kaspersky_opentip/kaspersky_opentip.py`,
`wazuh/wazuh.py`, `security_onion/security_onion.py`, `freeipa/freeipa.py`.

- [ ] `rstcloud`/`kaspersky_opentip`/`wazuh` — `_connect_impl` (у wazuh уже
      непустой — делает login) заводит `self._client =
      new_client(verify=self.verify_ssl)`; методы `_get`/`_put` переходят
      с `http_client_sync.get_json(url, ..., verify=self.verify_ssl)` на
      `self._client.get(url, headers=...).json()` (verify уже на
      инстансе, параметр из вызова убирается)
- [ ] `wazuh._connect_impl` — login-запрос тоже идёт через
      `self._client.post(url, json={}, headers={...}).json()["data"]["token"]`,
      не через модульный `http_client_sync`
- [ ] `security_onion.py` — `self._client = new_client(verify=self.verify_ssl)`
      в `_connect_impl` (сегодня использует модульный `http_client_sync`
      для всех методов, кроме `get_pcap`); `_search`/`get_agents`/
      `get_detections`/`get_hunts` переходят на `self._client`;
      `get_pcap` — `self._client.get(url, headers=self._headers()).content`,
      убрать собственный `with httpx.Client(...) as client:` блок и
      комментарий про "binary response — SyncHttpClient always parses
      JSON" (причина исчезла); убрать `import httpx` если после правки
      больше нигде в файле не используется напрямую (проверить)
- [ ] `freeipa.py` — `_connect_impl`: убрать прямой `httpx.Client(...)`
      login-блок и импорт `_validate_external_url`; `self._client =
      new_client(verify=self.verify_ssl)`, login —
      `self._client.post(login_url, data={...}, headers={"Content-Type":
      "application/x-www-form-urlencoded"})` (SSRF-guard теперь внутри
      `LoggingHttpClient.send`, не нужен отдельный вызов); убрать
      `_session_cookie`/`_headers()` целиком — cookie jar персистентен на
      `self._client` между login и `_api_call`; `_api_call` —
      `self._client.post(f"{self._base_url}/ipa/json", json=payload).json()`;
      убрать `import httpx` если не используется больше нигде в файле
      (проверить — вероятно да, весь прямой httpx уходит)
- [ ] Соответствующие тесты — `test_rstcloud_connector.py`,
      `test_kaspersky_opentip_connector.py`, `test_wazuh_connector.py`,
      `test_security_onion_connector.py`, `test_freeipa_connector.py`:
      мокать `soar.tools.http_client.new_client` (return_value — `MagicMock`
      с `.get`/`.post`/`.content`) вместо `http_client_sync`/голого
      `httpx.Client`
- [ ] `test_freeipa_connector.py` — новый/переписанный тест: login и
      следующий `_api_call` идут через один и тот же mock-объект
      `self._client` (проверка на persistent instance, не пересборку клиента
      каждый раз) — это прямая проверка success criteria спека ("persistent
      cookie jar", п. [S4])
- [ ] `test_security_onion_connector.py` — `get_pcap` больше не мокает
      отдельный голый `httpx.Client`, использует тот же `self._client` mock,
      что и остальные методы теста
- [ ] Confirm: тесты падают сразу после смены реализации, до правки тестов
      — затем зелёные

### 5.3 Манифест + прочее

- [ ] `python tools/gen_manifest.py --version <next>` (в
      `soar-content-pack`) — перегенерировать `manifest.yaml`: `freeipa` и
      `security_onion` теряют `httpx` из `imports:`, если `import httpx`
      реально убран из обоих файлов (см. 5.2); сверить diff вручную перед
      коммитом (это derived-артефакт, но версия/имя пака — решение,
      подтвердить `--version` с пользователем, не гадать номер)
- [ ] `grep -rn "http_client_sync\|get_json\|post_json\|put_json"
      connectors/` в `soar-content-pack` — пусто после миграции
      (success criteria спека)
- [ ] `grep -rn "_validate_external_url\|soar.tools.http_client import _"
      connectors/` — пусто (никто не импортирует `_`-префиксный символ
      напрямую)

## 6. Regression check (оба репозитория)

- [ ] `python -m pytest tests/soar/tools/ tests/orchestrator/test_introspect.py
      tests/orchestrator/api/test_tools_api.py tests/soar/test_runner.py -v`
      (в `soar`) — все новые и переписанные тесты зелёные
- [ ] `python -m pytest tests/ -q` (в `soar`) — без регрессий
      относительно текущего baseline; отдельно проверить
      `tests/orchestrator/api/test_connectors.py` (или где ещё вызывается
      `parse_classes`) не задет — сигнатура `parse_classes` не менялась
- [ ] `ruff check .` (в `soar`) — зелёный
- [ ] `cd ../soar-content-pack && python -m pytest tests/ -q` — все 10
      переписанных + 6 нетронутых (misp/mysql/shodan/smb_rpc/winrm — не в
      списке HTTP-коннекторов) тестов зелёные
- [ ] Ручная проверка `GET /tools` на реальном стенде (или через тест
      `test_real_soar_tools_dunder_all_excludes_internals` уже это
      покрывает статически) — 8 имён из `TOOL_REGISTRY`, ни одной записи с
      пустым `summary` без `error`

## Verification

- [ ] Все success criteria спека [S5] построчно проверены (7 пунктов) —
      сверить каждый явно, не полагаться на "тесты прошли значит всё ок"
      (например: "не содержит `async def`" — `grep -n "async def"
      soar/tools/http_client.py` должен быть пуст, отдельная явная
      проверка, не только вывод тестов)
- [ ] Написать отчёт `docs/compose/reports/tools-redesign.md` — что
      сделано, что отклонилось от спека (если было), результаты
      regression check
- [ ] После отчёта (не раньше — см. CLAUDE.md "не обновлять AGENTS.md
      заранее"): обновить `AGENTS.md`/`CHANGELOG.md` (новая версия,
      описание TOOL_REGISTRY/LoggingHttpClient/CachingHttpClient/new_client),
      и `docs/concepts/ENTITY-MODEL.md` часть 4 (чеклист), если задача
      закрывает какой-то из пунктов там
