# Tools: явный реестр, изоляция внутренностей, HTTP-клиент без async/JSON-only

> Архитектура согласована в обсуждении 2026-08-03 до написания этого спека
> (см. AskUserQuestion в сессии) — четыре развилки, все решены. Этот спек
> **отменяет** `docs/compose/specs/2026-07-31-tools-singleton-introspection-design.md`
> (Д4): та спека чинила ту же дыру набором AST-эвристик (class-name match →
> function-name match → instance-assignment inference → synthetic fallback)
> поверх `__all__`. Ниже вместо трёх эвристик — один явный реестр, который
> эвристики не нужны в принципе. Д4-спек оставлен как референс, не удалён
> (та же практика, что для `2026-07-03-bugfixes-design.md` и других
> отменённых спеков в `CLAUDE.md`).

## [S1] Problem

Три жалобы из ревью тулов — на самом деле одна причина: `soar/tools/__init__.py::__all__`
говорит **что** публично, но не **как** это интроспектировать, и
`orchestrator/core/introspect.py` вынужден угадывать форму по AST — и
угадывает неверно для всего, что не класс.

**1. Не видно, что импортировать.** `__all__` уже фильтрует вывод `GET
/tools` (E5, v0.18) — сторонние `CacheBackend`/`InMemoryCache`/`RedisCache`
в списке не показываются, это работает. Но 4 из 6 публичных имён —
`http_client`, `http_client_sync`, `watermark_store`, `seen_store` — не
классы, а инстанс/фабрики. `parse_classes` их не видит, и
`orchestrator/api/tools.py` возвращает для них синтетическую заглушку
`{"name": ..., "summary": ""}` — без докстринга, без сигнатуры, без
методов. Ровно то, что зафиксировано в Д4 (`docs/compose/reports/manual-qa-prod-onsite.md`,
"Пришлось прочитать `soar/tools/http_client.py` напрямую"), но там же не
исправлено.

**2. HTTP-клиент — "куча кода непонятно зачем" и только JSON.**
`HttpClient`/`SyncHttpClient` (`soar/tools/http_client.py`) — почти
идентичные по 70 строк класса, вручную дублирующие `get_json`/`post_json`/
`put_json`, каждый — руками собранные SSRF-guard + таймер + лог + кэш.
Ограничение на JSON — не гипотетическое, оно уже дважды обойдено вживую в
`soar-content-pack`:

- `security_onion.py:89-100::get_pcap` — бинарный ответ (pcap), `SyncHttpClient.get_json`
  всегда парсит JSON → метод уходит на голый `httpx.Client`, теряя единую
  точку лога (SSRF формально не теряется — `base_url` доверенный, но
  дисциплина "одна точка правды на все HTTP-вызовы" уже нарушена).
- `freeipa.py:32-53::_connect_impl` — сессионная кука, `SyncHttpClient`
  создаёт новый `httpx.Client` на каждый вызов (нет persistent cookie jar)
  → login делается вручную через `httpx.Client` + **прямой импорт**
  `soar.tools.http_client._validate_external_url` (внутренний
  helper, не в `__all__`) — живой пример того, что "нельзя импортировать
  другую внутрянку" сегодня не соблюдается никак, даже без злого умысла.

Проверено: асинхронный `HttpClient` не использует ни один из 24
коннекторов (`soar-content-pack`, `grep -r "await http_client\."` — пусто);
весь рантайм воркфлоу/экшенов/коннекторов синхронный
(`soar/workflows/base.py::BaseWorkflow.run`). Async-версия — мёртвый код,
который тем не менее удваивает площадь `http_client.py` и `__all__`.

**3. Watermark "ничего не понятно" — следствие (1), не отдельная
проблема.** `WatermarkStore`/`SeenStore` — классы, интроспектируются
нормально. `watermark_store`/`seen_store` — фабрики (`def
watermark_store(name)`), которые реально импортируют авторы (`from
soar.tools import watermark_store; ws = watermark_store("my_workflow")`) —
и это ровно то, что заглушка (1) прячет.

## [S2] Solution

### (a) Явный реестр вместо AST-эвристик

`soar/tools/__init__.py` — literal dict, единственный источник и для
`__all__`, и для `GET /tools`:

```python
TOOL_REGISTRY = {
    "http_client":        {"kind": "instance", "of": "LoggingHttpClient", "module": "http_client"},
    "LoggingHttpClient":   {"kind": "class", "module": "http_client"},
    "CachingHttpClient":   {"kind": "class", "module": "http_client"},
    "new_client":          {"kind": "factory", "module": "http_client"},
    "WatermarkStore":      {"kind": "class", "module": "watermark"},
    "SeenStore":           {"kind": "class", "module": "watermark"},
    "watermark_store":     {"kind": "factory", "module": "watermark"},
    "seen_store":          {"kind": "factory", "module": "watermark"},
}

__all__ = list(TOOL_REGISTRY)
```

`kind` — три значения, без дальнейшего роста: `class` (интроспектируется
`parse_classes` по имени как есть), `instance` (интроспектируется
`parse_classes` по имени класса из `of`, но карточка отдаётся под
публичным именем + полем `"instance_of"`), `factory` (интроспектируется
`parse_functions`, форма ответа — `{"kind": "function", "signature", "docstring"}`,
как уже есть в кодовой базе для `parse_functions`).

`orchestrator/core/introspect.py` — новая функция:

```python
def parse_tool_registry(init_path: Path) -> dict[str, dict]:
    """Read TOOL_REGISTRY = {...} literal dict via AST — no import."""
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "TOOL_REGISTRY":
                return ast.literal_eval(node.value)
    return {}
```

`orchestrator/api/tools.py` — резолв по `kind`, без синтетического
fallback (реестр по построению покрывает 100% публичных имён — если имя в
`TOOL_REGISTRY`, оно резолвится однозначно одним из трёх путей, ветка
"ничего не нашли" остаётся только на случай битого файла инструмента и
должна логироваться как ошибка конфигурации, не тихо отдаваться в UI):

```python
@router.get("")
async def list_tools(request: Request):
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    registry = parse_tool_registry(tools_dir / "__init__.py")
    return [_resolve(tools_dir, name, meta) for name, meta in registry.items()]

def _resolve(tools_dir: Path, name: str, meta: dict) -> dict:
    module_file = tools_dir / f"{meta['module']}.py"
    if meta["kind"] == "class":
        entry = next((c for c in parse_classes(module_file) if c["name"] == name), None)
    elif meta["kind"] == "instance":
        cls = next((c for c in parse_classes(module_file) if c["name"] == meta["of"]), None)
        entry = {**cls, "name": name, "instance_of": meta["of"]} if cls else None
    else:  # factory
        fn = next((f for f in parse_functions(module_file) if f["name"] == name), None)
        entry = {**fn, "kind": "function"} if fn else None
    return entry or {"name": name, "module": meta["module"], "summary": "", "error": "unresolved"}
```

`GET /tools/{name}` — тот же `_resolve`, один элемент вместо списка.
Побочный эффект: Д4-пункт (a) (расширить `parse_classes` на `async def`
методы) становится **не нужен** — раз async-клиент удаляется целиком (см.
(c)), в `soar/tools/` больше не остаётся ни одного `async def`, чинить
нечего.

### (b) Внутренняя механика — в `_*.py`

`orchestrator/api/tools.py` уже пропускает файлы с `_`-префиксом
(`tools.py:26`, не трогается) — это делает конвенцию "внутреннее — в
`_*.py`" (уже принятую для `orchestrator/core/` vs приватные хелперы,
`CLAUDE.md`) действующей и для `soar/tools/` бесплатно.

- `soar/tools/_cache.py` (новый) — `CacheBackend`, `InMemoryCache`,
  `RedisCache`, без изменений в реализации, только перенос.
- `soar/tools/_net.py` (новый) — `_is_private_ip`, `_validate_external_url`,
  `_log_safe_url`, без изменений в реализации, только перенос.
- Не хард-барьер (Python не мешает `from soar.tools._net import
  _validate_external_url`), а конвенция+видимость в API/UI — тот же баланс,
  что уже принят в проекте для остальных `_*.py` (граница зависимостей, не
  песочница). Разница с текущим состоянием: после (c) ниже
  `_validate_external_url` никому вне `http_client.py` не нужен — `freeipa`
  перестаёт быть исключением, которое его импортирует (см. (d)/(g)).

### (c) `LoggingHttpClient`/`CachingHttpClient` — подкласс `httpx.Client`

Вместо ручного дублирования `get_json`/`post_json`/`put_json` — override
`send()`, единая точка для ЛЮБОГО HTTP-метода (`get`/`post`/`put`/`delete`/
`head`/...), унаследованного от `httpx.Client` целиком:

```python
class LoggingHttpClient(httpx.Client):
    """Прозрачный лог + SSRF-guard на каждый запрос, любой httpx.Client
    метод. Не JSON-специфичен: .get(url).json() для JSON-API,
    .get(url).content для бинарных ответов (pcap и т.п.) — то же, что
    голый httpx.Client, но пропущенное через одну точку правды."""

    def __init__(self, **kwargs):
        kwargs.setdefault("timeout", 30)
        kwargs.setdefault("follow_redirects", False)  # SSRF: не даём редиректу обойти guard
        super().__init__(**kwargs)

    def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        _validate_external_url(str(request.url))
        start = time.monotonic()
        response = super().send(request, **kwargs)
        duration_ms = int((time.monotonic() - start) * 1000)
        _log.info(
            f"http {request.method} {_log_safe_url(str(request.url))} "
            f"status={response.status_code} duration_ms={duration_ms}"
        )
        response.raise_for_status()  # тот же контракт, что get_json/post_json сегодня
        return response


class CachingHttpClient(LoggingHttpClient):
    """LoggingHttpClient + опциональный кэш GET-ответов. POST/PUT/DELETE
    никогда не кэшируются (мутация по определению — тот же принцип, что
    сегодня)."""

    def __init__(self, cache: CacheBackend | None = None, default_ttl: int = 3600,
                 domain_ttl: dict[str, int] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._cache = cache
        self._default_ttl = default_ttl
        self._domain_ttl = domain_ttl or {}

    def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        if request.method != "GET" or self._cache is None:
            return super().send(request, **kwargs)
        key = _cache_key(str(request.url), dict(request.headers))
        if (hit := self._cache.get(key)) is not None:
            _log.debug(f"http cache hit: {_log_safe_url(str(request.url))}")
            return httpx.Response(hit["status"], content=hit["content"], headers=hit["headers"], request=request)
        response = super().send(request, **kwargs)  # логирует + raise_for_status внутри
        self._cache.set(key, {
            "status": response.status_code, "content": response.content, "headers": dict(response.headers),
        }, _ttl_for(self._domain_ttl, self._default_ttl, str(request.url), None))
        return response
```

Важные решения внутри этого куска (чтобы не удивляться на этапе плана):

- **Лог — до `raise_for_status()`, не после.** Порядок в `LoggingHttpClient.send`
  принципиален: если поменять местами, ошибочные (4xx/5xx) запросы
  перестанут логироваться — а "безусловно один лог на запрос" был
  исходным требованием P12 (`http_client.py` докстринг сегодня). `raise_for_status()`
  после лога сохраняет то же поведение вызова, что `get_json`/`post_json`
  дают сейчас (исключение на ошибочный статус), только не через
  `event_hooks` — они срабатывают раньше нашего лога и убили бы гарантию.
- **Кэшируются только успешные ответы** — `raise_for_status()` кидает
  исключение внутри `super().send()` до того, как `CachingHttpClient.send`
  дойдёт до `self._cache.set(...)`, тот же эффект, что сейчас (кэш
  наполняется только для 2xx), без явной проверки статуса.
- **`cached=`/`ttl=` per-call параметры не переносятся.** Ни один из 10
  HTTP-коннекторов в `soar-content-pack` их не использует (`grep -rn
  "cached=\|ttl=" connectors/` — пусто). Политика кэша — на уровне клиента
  (`default_ttl`/`domain_ttl` в конструкторе), не на уровне вызова —
  проще, "прозрачно" в буквальном смысле (нет параметров, о которых нужно
  помнить на каждом call site). Если понадобится point-in-time bypass —
  добавить отдельным треком, когда появится реальный потребитель, не
  сейчас (YAGNI).
- **`verify` — параметр конструктора клиента, не параметр вызова.**
  У `httpx.Client` (в отличие от старого `SyncHttpClient.get_json(...,
  verify=...)`, который пересобирал `httpx.Client` на каждый вызов) `verify`
  фиксируется один раз при создании инстанса. Прямое следствие для (g):
  5 из 10 коннекторов, которым нужен `verify_ssl=False` per-instance,
  больше не могут просто звать общий синглтон — заводят свой инстанс через
  `new_client()` (ниже).

### (d) `new_client()` — для инстансов вне общего синглтона

Коннекторам с нестандартным TLS-доверием (`verify_ssl` в конфиге) или
persistent state (cookie jar, как `freeipa`) общий синглтон не подходит —
конструктор клиента фиксирует `verify` раз и навсегда. `new_client()` даёт
такой инстанс, но с той же кэш/лог-конфигурацией, что и общий синглтон
(не пересобирает кэш с нуля на каждый вызов — один `CacheBackend`-инстанс
на процесс, тот же принцип, что уже есть в `runner.py::_build_http_client_sync`
сегодня):

```python
# soar/tools/http_client.py — заполняется soar/runner.py при старте процесса,
# тем же способом, что и синглтон http_client (см. (e))
_shared_cache: CacheBackend | None = None
_shared_default_ttl: int = 3600
_shared_domain_ttl: dict[str, int] = {}


def new_client(verify: bool = True) -> LoggingHttpClient:
    """Клиент с той же лог/кэш-конфигурацией, что и синглтон http_client,
    но собственным TLS-доверием — для коннекторов, которым нужен
    verify_ssl=False или persistent-инстанс (cookie jar). Держать инстанс
    в self._client коннектора (_connect_impl), не создавать заново на
    каждый вызов."""
    if _shared_cache is None:
        return LoggingHttpClient(verify=verify)
    return CachingHttpClient(
        cache=_shared_cache, default_ttl=_shared_default_ttl,
        domain_ttl=_shared_domain_ttl, verify=verify,
    )
```

### (e) `soar/runner.py` — упрощение сборки

Один клиент вместо двух (`http_client`/`http_client_sync` схлопываются —
асимметрия исчезает вместе с async-версией):

```python
def _build_http_client(config: dict) -> LoggingHttpClient:
    http_cfg = config.get("http_client", {})
    cache = _build_cache(http_cfg, config.get("queue", {}))  # без изменений
    default_ttl = http_cfg.get("default_ttl", 3600)
    domain_ttl = http_cfg.get("domain_ttl", {})
    http_client.http_client._shared_cache = cache
    http_client.http_client._shared_default_ttl = default_ttl
    http_client.http_client._shared_domain_ttl = domain_ttl
    if cache is None:
        return LoggingHttpClient()
    return CachingHttpClient(cache=cache, default_ttl=default_ttl, domain_ttl=domain_ttl)


tools.http_client = _build_http_client(config)
```

`_build_http_client_sync` удаляется целиком. Порядок (до
`workflows.init()`/`connectors.init()`/`actions.init()`) не меняется — та
же причина, что в `2026-07-28-http-client-init-order-design.md`.

### (f) `soar/tools/watermark.py`

Без изменений — уже корректно устроен, просто теперь честно
интроспектируется через (a).

### (g) Миграция `soar-content-pack` (отдельный репозиторий)

Решено (см. AskUserQuestion) — полный переход, `get_json`/`post_json`/
`put_json` не остаются как сахар. 10 файлов, два паттерна:

**Простая замена** (`abusech`, `censys`, `crtsh`, `fofa`, `urlhaus` — не
используют `verify=` per-call, остаются на общем `soar.tools.http_client`
синглтоне):
`http_client_sync.get_json(url, headers=h)` → `http_client.get(url, headers=h).json()`,
`http_client_sync.post_json(url, data, headers=h)` → `http_client.post(url, json=data, headers=h).json()`.
Импорт `from soar.tools import http_client_sync` → `from soar.tools import http_client`.

**Свой инстанс** (`rstcloud`, `kaspersky_opentip`, `security_onion`,
`wazuh`, `freeipa` — используют `verify=self.verify_ssl` per-call сегодня):
`_connect_impl` заводит `self._client = new_client(verify=self.verify_ssl)`
(вместо `pass` или ручного login), остальные методы вызывают
`self._client.get(...)`/`self._client.post(...)`. Конкретно:

- `security_onion.py::get_pcap` — уходит спецкейс на голый `httpx.Client`:
  `self._client.get(url, headers=self._headers()).content` — тот же
  `self._client`, что и остальные методы этого коннектора, один лог/SSRF
  путь на весь коннектор вместо двух.
- `freeipa.py::_connect_impl` — уходит прямой импорт `_validate_external_url`
  **и** ручная пересылка `Cookie`-заголовка: `self._client` — обычный
  `httpx.Client` (подкласс), у него есть cookie jar, персистентный между
  вызовами на одном инстансе. Login (`self._client.post(login_url,
  data=...)`) и последующие JSON-RPC-вызовы (`self._client.post(rpc_url,
  json=payload)`) идут через один и тот же `self._client` — кука
  подхватывается автоматически, `_headers()`/`_session_cookie` (`freeipa.py:29,55-58`)
  удаляются целиком, не только правятся.
- `wazuh.py::_put` (единственный потребитель `put_json`) —
  `self._client.put(url, headers=h).json()`.

Это правки в отдельном (локальном, без remote) репозитории
`soar-content-pack` — без своего spec-процесса (нет `docs/` там,
подтверждено). Выполняются тем же треком (план ниже покрывает оба
репозитория как последовательные шаги), не отдельной задачей.

## [S3] Regression check

- `GET /connectors/.../describe` и остальные потребители `parse_classes`
  (`orchestrator/api/connectors.py`) не задеты — сигнатура `parse_classes`
  не меняется, только кто её вызывает в `tools.py`.
- Убрать `async def` поддержку из Д4 нет нужды добавлять — `parse_classes`
  остаётся как есть (только `ast.FunctionDef`), потому что async-методов в
  `soar/tools/` после (c) не остаётся вообще.
- `_key`/`_ttl_for` в старом `HttpClient`/`SyncHttpClient` были bound
  methods; в новой версии — module-level `_cache_key`/`_ttl_for` (то же
  решение, что уже предлагалось, но не было реализовано, в
  `2026-07-28-http-client-sync-facade-design.md` [S2] — "решается на этапе
  плана", теперь решено).
- Кэш **общий** между `http_client` синглтоном и всеми `new_client()`
  инстансами (один `CacheBackend`, см. `_shared_cache`) — не регрессия
  относительно сегодняшнего дня, тот же принцип, что
  `_build_http_client_sync` уже соблюдает (один `CacheBackend` на оба
  старых синглтона).
- `response.raise_for_status()` внутри `send()` — поведенческая гарантия
  не меняется (`get_json`/`post_json` тоже кидали на не-2xx), но теперь она
  действует и для `.get()`/`.post()`, вызванных напрямую — если где-то в
  будущем понадобится терпимо обработать 4xx без исключения, это отдельная
  задача (сегодня ни один коннектор так не делает — проверено).
- `follow_redirects=False` — было per-call, стало client-level default
  (`__init__`). Поведенчески то же самое (SSRF защита от редиректа
  сохраняется), но теперь нельзя случайно забыть передать флаг на новом
  call site — не ослабление, усиление.
- `tests/soar/tools/test_http_client.py` — полностью переписывается
  (мокает `httpx.AsyncClient`/`httpx.Client` контекст-менеджеры старого
  API), не патчится инкрементально.
- `orchestrator/api/tools.py`/`tests/orchestrator/api/test_tools_api.py` —
  8 текущих тестов почти все переписываются (текущая фикстура строит
  `__init__.py` с `__all__`, не `TOOL_REGISTRY`) — не point-fix.

## [S4] Testing Strategy

- `tests/soar/tools/test_http_client.py` — по одному тесту на:
  безусловный лог (успех и ошибка — оба логируют, ошибка после лога
  кидает), SSRF-guard (приватный IP → `ValueError` до отправки), кэш-хит
  не долетает до сети (мокнутый `httpx.Client.send` не вызывается),
  кэш-промах наполняет кэш только на 2xx, `POST` никогда не кэшируется,
  `verify` передаётся в конструктор и держится на инстансе.
- `tests/soar/tools/test_new_client.py` (новый) — `new_client()` до
  `runner.py`-инициализации (не в `soar-content-pack`, отдельно тестируемо)
  возвращает `LoggingHttpClient` без кэша; после — `CachingHttpClient` с
  тем же `_shared_cache`, что и `tools.http_client`.
- `tests/orchestrator/test_introspect.py` — `parse_tool_registry` на
  синтетическом `__init__.py` с `TOOL_REGISTRY`: `kind=class`/`instance`/
  `factory`, плюс негативный случай (имя в реестре, но файл/класс не
  существует → `error: "unresolved"`, не тихий синтетический fallback).
- `tests/orchestrator/api/test_tools_api.py` — по тесту на каждый `kind`:
  `GET /tools/http_client` (`instance`) отдаёт докстринг+методы
  `LoggingHttpClient` под именем `http_client`+`instance_of`; `GET
  /tools/watermark_store` (`factory`) отдаёт сигнатуру фабрики; `GET
  /tools/WatermarkStore` (`class`, регрессия) остаётся зелёным.
- `soar-content-pack/tests/` (отдельный репозиторий) — существующие тесты
  коннекторов (`test_abusech_connector.py` и т.п.) переписываются на мок
  `soar.tools.http_client.get`/`.post` вместо `.get_json`/`.post_json`;
  `test_freeipa_connector.py` — новый тест на persistent cookie jar
  (login + следующий вызов на одном `self._client`, без ручной пересылки
  заголовка); `test_security_onion_connector.py` — `get_pcap` больше не
  мокает отдельный голый `httpx.Client`.

## [S5] Success Criteria

- [ ] `GET /tools` — все 8 имён из `TOOL_REGISTRY` отдают непустой
      `summary`/сигнатуру, ни одной синтетической заглушки `{"summary": ""}`
- [ ] `soar/tools/http_client.py` не содержит `async def`; `HttpClient`
      (старый, async) и `SyncHttpClient` не существуют
- [ ] `soar/tools/_cache.py`/`_net.py` существуют, `http_client.py` их
      импортирует, `CacheBackend`/`InMemoryCache`/`RedisCache`/`_validate_external_url`
      не фигурируют ни в `TOOL_REGISTRY`, ни в выводе `GET /tools`
- [ ] Ни один файл в `soar-content-pack/connectors/` не импортирует
      `soar.tools.http_client._validate_external_url` или другой
      `_`-префиксный символ напрямую
- [ ] `security_onion.py::get_pcap` и `freeipa.py::_connect_impl` не
      содержат собственного `httpx.Client(...)` — оба используют
      `self._client`/`new_client()`
- [ ] Все 10 HTTP-коннекторов в `soar-content-pack` используют
      `.get()`/`.post()`/`.put()` + `.json()`/`.content`, ни один не
      ссылается на `get_json`/`post_json`/`put_json`
- [ ] Полный набор тестов (оба репозитория) проходит без регрессий
