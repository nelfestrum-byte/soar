# `HttpClient` Sync Facade + TI Connector Migration (S1)

> Реализует S1 из `docs/concepts/BAGFIX_PLAN.md`. Закрывает P12
> (`docs/concepts/UPGRADE-v2.md`) по факту, не только "тул поставлен" —
> даёт коннекторам реальную возможность вызвать `HttpClient` из
> синхронного кода, и переносит 3 TI-коннектора на него как образец.

## [S1] Problem

`soar/tools/http_client.py::HttpClient.get_json`/`post_json` — `async def`
поверх `httpx.AsyncClient`. Единственные упоминания `http_client` в
`soar/` — сам модуль, `soar/tools/__init__.py` (синглтон) и
`soar/runner.py` (сборка синглтона из конфига). Ни один из 24
коннекторов его не использует: все синхронные, все ходят через `requests`
(TI-коннекторы: `abusech`, `urlhaus`, `rstcloud`, `kaspersky_opentip`,
`crtsh`) либо через SDK/протокольные клиенты (`virus_total` → `vt`,
`shodan`/`fofa`/`censys` → свои SDK/`requests`).

Причина — не забывчивость, а несовместимость контрактов:
`BaseWorkflow.run()` (`soar/workflows/base.py:26`) — синхронный метод,
`soar/runner.py::main()` вызывает `workflows.execute()` тоже синхронно,
без event loop. Синхронный метод коннектора (например
`RstCloudConnector.check_ip()`) не может сделать `await
http_client.get_json(...)` — это синтаксическая ошибка вне `async def`;
обернуть в `asyncio.run(...)` на каждый вызов работало бы, но плодит
event loop на каждый HTTP-запрос ради одного `await` и не решает
проблему архитектурно (следующий вызов той же workflow — снова новый
loop). Ничего в `HttpClient` не вызывается — TI-запросы продолжают идти
через голый `requests` без кэша и без единого лога, ради которых P12
писался.

## [S2] Solution

Добавить `SyncHttpClient` — параллельную реализацию с тем же публичным
контрактом (`get_json`/`post_json`, та же сигнатура минус `await`),
поверх `httpx.Client` (синхронный), не обёртку над существующим async
`HttpClient` через `asyncio.run()`. Обоснование выбора (не обёртка):

- `asyncio.run()` на каждый вызов создаёт и уничтожает event loop —
  накладные расходы без выгоды (внутри одного sync-вызова нет
  конкурентности, которой event loop мог бы помочь).
- `asyncio.run()` падает с `RuntimeError`, если вызван из кода, который
  сам уже выполняется внутри работающего event loop — на сегодня в
  `soar/runner.py` такого нет, но это скрытая мина на будущее (если
  когда-нибудь появится async workflow support).
- Переиспользовать код есть что: `CacheBackend`/`InMemoryCache`/
  `RedisCache` (`http_client.py:27-69`) уже полностью синхронны
  (`get`/`set` — не `async def`) — используются обеими реализациями без
  изменений. `_is_private_ip`/`_validate_external_url`
  (`http_client.py:72-105`) — тоже чистые синхронные функции, без
  изменений.

```python
class SyncHttpClient:
    """Синхронный близнец HttpClient — тот же контракт логирования/кэша/
    SSRF-guard, для вызова из синхронных методов коннекторов (весь
    существующий рантайм workflow/actions/connectors сегодня синхронный,
    см. soar/workflows/base.py::BaseWorkflow.run). Не обёртка над
    HttpClient через asyncio.run() — см. docs/compose/specs/
    2026-07-28-http-client-sync-facade-design.md [S2] почему."""

    def __init__(
        self,
        cache: CacheBackend | None = None,
        default_ttl: int = 3600,
        domain_ttl: dict[str, int] | None = None,
    ) -> None:
        self._cache = cache
        self._default_ttl = default_ttl
        self._domain_ttl = domain_ttl or {}

    _key = HttpClient._key          # переиспользуем как есть — чистая функция
    _ttl_for = HttpClient._ttl_for  # (либо вынести обе в module-level функции,
                                     #  решить на этапе плана — то же тело,
                                     #  без self.-зависимого состояния кроме
                                     #  _domain_ttl/_default_ttl, которые тоже
                                     #  идентичны по форме)

    def get_json(
        self, url: str, headers: dict | None = None,
        ttl: int | None = None, cached: bool = True,
    ) -> dict:
        headers = headers or {}
        _validate_external_url(url)
        key = self._key(url, headers) if self._cache and cached else None
        if key and (hit := self._cache.get(key)) is not None:
            _log.debug(f"http cache hit: {url}")
            return hit
        start = time.monotonic()
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, headers=headers, follow_redirects=False)
            resp.raise_for_status()
        duration_ms = int((time.monotonic() - start) * 1000)
        _log.info(f"http GET {url} status={resp.status_code} duration_ms={duration_ms}")
        data = resp.json()
        if key:
            self._cache.set(key, data, self._ttl_for(url, ttl))
        return data

    def post_json(self, url: str, payload: dict, headers: dict | None = None) -> dict:
        _validate_external_url(url)
        start = time.monotonic()
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload, headers=headers or {}, follow_redirects=False)
            resp.raise_for_status()
        duration_ms = int((time.monotonic() - start) * 1000)
        _log.info(f"http POST {url} status={resp.status_code} duration_ms={duration_ms}")
        return resp.json()
```

Точная механика переиспользования `_key`/`_ttl_for` (bound method
reference на другой класс работает в Python, т.к. обе не используют
`self` за пределами атрибутов с одинаковыми именами — но не идиоматично)
решается на этапе плана: скорее всего вынести оба метода в
module-level функции `_cache_key(url, headers)`/`_ttl_for(domain_ttl,
default_ttl, url, ttl)`, вызываемые из обоих классов — чище, чем
межклассовое переиспользование метода.

## [S3] Wiring (`soar/tools/__init__.py`, `soar/runner.py`)

```python
# soar/tools/__init__.py
from soar.tools.http_client import HttpClient, SyncHttpClient

http_client = HttpClient()            # существующий async синглтон, не трогаем
http_client_sync = SyncHttpClient()   # NEW — sync синглтон, тот же паттерн
```

`soar/runner.py::_build_http_client()` разбивается на конструирование
общего `cache` один раз и передачу его в оба синглтона (один и тот же
`CacheBackend`-инстанс — синхронный `InMemoryCache`/`RedisCache` не имеет
проблем с использованием из обоих клиентов, кэш общий по домену
независимо от того, каким клиентом получен hit):

```python
def _build_cache(http_cfg: dict, queue_cfg: dict) -> CacheBackend | None:
    cache_backend = http_cfg.get("cache_backend", "memory")
    if cache_backend == "memory":
        return InMemoryCache()
    elif cache_backend == "redis":
        redis_url = queue_cfg.get("redis_url", "")
        if not redis_url:
            raise ValueError("http_client.cache_backend is 'redis' but queue.redis_url is empty")
        return RedisCache(redis_url)
    elif cache_backend == "none":
        return None
    raise ValueError(f"Unknown http_client.cache_backend: {cache_backend!r}")


cache = _build_cache(config.get("http_client", {}), config.get("queue", {}))
default_ttl = config.get("http_client", {}).get("default_ttl", 3600)
domain_ttl = config.get("http_client", {}).get("domain_ttl", {})

tools.http_client = HttpClient(cache=cache, default_ttl=default_ttl, domain_ttl=domain_ttl)
tools.http_client_sync = SyncHttpClient(cache=cache, default_ttl=default_ttl, domain_ttl=domain_ttl)
```

Эта же правка places `tools.http_client`/`tools.http_client_sync` в одно
место с [S2] из S2-спеки этого трека
(`docs/compose/specs/2026-07-28-http-client-init-order-design.md`,
она же закрывает отдельный баг с порядком инициализации) — обе правки
трогают один и тот же блок `runner.py`, делать последовательно на этапе
плана, не одновременно, чтобы diff каждой оставался читаемым отдельно.

## [S4] Connector Migration — образец, 3 коннектора

Мигрируются как образец (демонстрируют оба паттерна аутентификации —
без auth, Bearer, custom header — и оба метода — GET, POST):

- **`abusech`** (`soar/connectors/abusech/abusech.py`) — `requests.Session`
  + `POST` без авторизации → `http_client_sync.post_json(url, data)`.
  `_session`/`_connect_impl`/`disconnect` уходят целиком — `HttpClient`
  не держит персистентной сессии (создаёт `httpx.Client` per-request,
  см. [S2]), коннектор перестаёт нуждаться в `_connect_impl` для HTTP
  части. `_ensure_connected()`/`is_connected` — оставить как no-op
  (`_connected = True` в `_connect_impl`), чтобы не ломать
  `BaseConnector` контракт (`_ensure_connected()` вызывается перед каждым
  публичным методом во всех коннекторах — трогать этот паттерн не в
  скоупе этого трека).
- **`rstcloud`** (`soar/connectors/rstcloud/rstcloud.py`) — `GET` +
  `Authorization: Bearer {api_key}` заголовок, собираемый один раз в
  `_connect_impl` в `_session.headers` → переносится в `headers=`,
  передаваемый на каждый вызов `http_client_sync.get_json(url,
  headers={"Authorization": f"Bearer {self.api_key}", "User-Agent":
  "SOAR-Connector/1.0"})`. `verify_ssl` — `SyncHttpClient.get_json` не
  принимает `verify` параметр сегодня (`httpx.Client(timeout=30)` без
  `verify=`) — добавить параметр `verify: bool = True` в
  `SyncHttpClient.get_json`/`post_json`, прокидываемый в
  `httpx.Client(timeout=30, verify=verify)`; иначе `rstcloud`/
  `kaspersky_opentip` теряют существующую возможность отключить проверку
  сертификата (`verify_ssl: false` в конфиге — нужна для part приватных
  инсталляций opentip за self-signed сертификатом, не убирать при
  миграции).
- **`kaspersky_opentip`** (`soar/connectors/kaspersky_opentip/
  kaspersky_opentip.py`) — тот же паттерн, что `rstcloud`, но
  `X-Api-Key` вместо `Authorization: Bearer` — второй пример
  custom-header авторизации, показывает что миграция не завязана на
  конкретную auth-схему.

`urlhaus`/`crtsh` **не мигрируются** в этом треке — оставлены как
дальнейший образец по той же схеме (S8 backlog, не блокирует закрытие
S1); 3 коннектора уже покрывают оба HTTP-метода и оба типа
auth-заголовков, этого достаточно, чтобы P12 перестал быть "тул без
потребителей" и появился воспроизводимый паттерн миграции для
оставшихся.

`virus_total`/`shodan`/`fofa`/`censys`/`misp` — используют
специализированные SDK (`vt`, `shodan`, собственные клиенты) — миграция
на `HttpClient` означала бы переписать поверх голых REST-эндпоинтов,
теряя SDK-функциональность (retry, pagination helpers), что не входит в
задачу P12 ("TI-запросы без кэша и без лога") и не рассматривается в
этом треке.

## [S5] Testing Strategy

`tests/soar/tools/test_http_client.py`:

- Зеркальные тесты для `SyncHttpClient` на каждый существующий async-тест
  (`get_json` — базовый запрос/лог, cache hit, `cached=False` bypass,
  SSRF-guard на приватный IP; `post_json` — базовый запрос, SSRF-guard):
  `patch("soar.tools.http_client.httpx.Client", return_value=client_ctx)`
  вместо `httpx.AsyncClient`, без `await`/`pytest.mark.asyncio`.
- Тест на `verify_ssl=False` — проверить, что `httpx.Client` получает
  `verify=False` при явной передаче.

`tests/soar/test_abusech_connector.py`, `test_rstcloud_connector.py`,
`test_kaspersky_opentip_connector.py` — заменить моки `requests.Session`
на моки `soar.tools.http_client_sync` (`patch.object(http_client_sync,
"post_json", return_value=...)` и т.п.); утверждения о возвращаемых
данных не меняются — контракт метода коннектора (`get_malware_iocs`,
`check_ip`, ...) наружу тот же.

## [S6] Success Criteria

- [ ] `SyncHttpClient` — тот же публичный контракт, что и `HttpClient`
      (минус `await`), то же безусловное логирование, тот же
      SSRF-guard, тот же опциональный кэш (переиспользует
      `CacheBackend`/`InMemoryCache`/`RedisCache` без изменений)
- [ ] `soar.tools.http_client_sync` собирается в `runner.py` из того же
      `http_client:` конфига, что и `soar.tools.http_client`, с общим
      `cache`-инстансом
- [ ] `abusech`/`rstcloud`/`kaspersky_opentip` используют
      `http_client_sync` вместо голого `requests`/`requests.Session`;
      публичные методы коннекторов не меняют сигнатуру/поведение для
      вызывающих workflow
- [ ] `verify_ssl: false` в конфиге `rstcloud`/`kaspersky_opentip`
      продолжает работать через новый `verify` параметр
- [ ] `docs/concepts/UPGRADE-v2.md` P12 переформулирован с "Реализовано"
      на состояние после этого фикса — тул есть, потребители есть,
      адаптация остальных TI-коннекторов — задокументированный backlog,
      не блокер (см. D5, правится вместе с этим треком)
