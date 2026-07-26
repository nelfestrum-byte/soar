# HTTP Client Tool: Logging + Optional Caching

> Реализует P12 из `docs/concepts/UPGRADE-v2.md`. Заменяет Feature 1
> (`CachedHttpClient`) из `docs/compose/specs/2026-07-03-v06-upgrade-design.md`
> (`[S4]`) — та спека написана 2026-07-03, ни разу не реализована (`grep`
> по репозиторию на `CachedHttpClient`/`http_client`/`HttpCache` даёт
> совпадения только в документации, не в коде). Feature 2 (per-workflow
> метрики в `/status`) и Feature 3 (dry-run конвенция) v0.6-спеки остаются
> в её собственном скоупе, этой спекой не затрагиваются.

## [S1] Problem

Threat-intel actions (VT, AbuseCh, Kaspersky, RST, URLhaus, Shodan, Fofa,
Censys, crt.sh, MISP) делают HTTP-запросы к внешним API напрямую (`httpx`/
`requests` внутри каждого коннектора), без общего логирования и без кэша:

1. Одинаковые запросы (например, повторный enrichment одного и того же
   IOC в разных прогонах workflow) повторяются каждый раз — квоты внешних
   API (многие threat-intel сервисы rate-limit на бесплатных/базовых
   тарифах) расходуются на дублирующиеся запросы.
2. Нет единой точки логирования enrichment-вызовов — при разборе
   инцидента постфактум невозможно быстро увидеть, какие внешние запросы
   сделал workflow, с каким результатом и когда, не залезая в лог каждого
   коннектора отдельно (см. известное ограничение "лог джобы — неструктурированный
   текст", `UPGRADE.md` P11).

## [S2] Solution Overview

Один класс `HttpClient` в `soar/tools/http_client.py` — не два класса
("logging" и "logging+caching"), а один с опциональным кэш-бэкендом и
per-call флагом `cached`:

- Логирование — **всегда**, безусловно, независимо от того, настроен ли
  кэш. Один лог-вызов на запрос через `loguru` (метод, домен, статус,
  duration_ms, cache_hit) — та же философия "одна строка лога на запрос",
  что уже применена в `access_log_middleware` (`orchestrator/main.py`),
  для симметрии между HTTP-слоем оркестратора и HTTP-слоем soar-действий.
- Кэш — опциональный. Если `HttpClient` сконструирован без `cache=...`
  (или `cache_backend: none` в конфиге) — работает как чистый
  логирующий прокси, `cached=True` по умолчанию на вызовах становится
  no-op (нет бэкенда — нечего кэшировать). Если бэкенд задан — `cached`
  на конкретном вызове позволяет обойти кэш точечно (например, для
  повторной проверки заведомо изменившегося индикатора).
- Это даёт то же практическое разделение "logging-only" vs
  "logging+caching", что и два отдельных класса, без дублирования кода
  HTTP-транспорта/логирования между ними — один код пути запроса, один
  набор тестов на него.

## [S3] Architecture

```
soar/
├── tools/
│   ├── __init__.py               # MODIFY: экспорт http_client singleton
│   └── http_client.py            # NEW: HttpClient, CacheBackend, InMemoryCache, RedisCache
├── runner.py                     # MODIFY: инициализация http_client singleton
│                                  #         из SOAR_CONFIG (тот же паттерн, что config чтение)
└── connectors/.../*.py            # NOT modified this spec — миграция существующих
                                    # connector'ов на HttpClient вместо прямых httpx-вызовов
                                    # это отдельный план, не часть этой спеки (см. S9)

orchestrator/
└── config.py                      # MODIFY: HttpClientConfig, поле OrchestratorConfig.http_client
```

## [S4] `HttpClient` Design

```python
# soar/tools/http_client.py
import hashlib
import time
from typing import Protocol

import httpx
from loguru import logger as _log


class CacheBackend(Protocol):
    def get(self, key: str) -> dict | None: ...
    def set(self, key: str, value: dict, ttl: int) -> None: ...


class InMemoryCache:
    """TTL-кэш в памяти процесса (per-worker, не шарится между subprocess'ами).
    Достаточно для одного workflow-запуска — каждый subprocess живёт одну джобу."""
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, dict]] = {}

    def get(self, key: str) -> dict | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: dict, ttl: int) -> None:
        self._store[key] = (time.monotonic() + ttl, value)


class RedisCache:
    """Опциональный бэкенд для разделяемого кэша между воркерами.
    Ключ: soar:httpcache:{sha256(url+headers)[:16]}. Тот же redis_url,
    что и очередь (queue.redis_url), отдельный клиент."""
    def __init__(self, redis_url: str) -> None:
        import redis
        self._client = redis.from_url(redis_url)

    def get(self, key: str) -> dict | None:
        import json
        raw = self._client.get(f"soar:httpcache:{key}")
        return json.loads(raw) if raw else None

    def set(self, key: str, value: dict, ttl: int) -> None:
        import json
        self._client.setex(f"soar:httpcache:{key}", ttl, json.dumps(value))


class HttpClient:
    def __init__(
        self,
        cache: CacheBackend | None = None,
        default_ttl: int = 3600,
        domain_ttl: dict[str, int] | None = None,
    ) -> None:
        self._cache = cache
        self._default_ttl = default_ttl
        self._domain_ttl = domain_ttl or {}

    def _key(self, url: str, headers: dict) -> str:
        raw = url + str(sorted(headers.items()))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _ttl_for(self, url: str, ttl: int | None) -> int:
        if ttl is not None:
            return ttl
        domain = httpx.URL(url).host
        return self._domain_ttl.get(domain, self._default_ttl)

    async def get_json(
        self, url: str, headers: dict | None = None,
        ttl: int | None = None, cached: bool = True,
    ) -> dict:
        headers = headers or {}
        _validate_external_url(url)
        key = self._key(url, headers) if self._cache and cached else None
        if key:
            if (hit := self._cache.get(key)) is not None:
                _log.debug(f"http cache hit: {url}")
                return hit
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, follow_redirects=False)
            resp.raise_for_status()
        duration_ms = int((time.monotonic() - start) * 1000)
        _log.info(f"http GET {url} status={resp.status_code} duration_ms={duration_ms}")
        data = resp.json()
        if key:
            self._cache.set(key, data, self._ttl_for(url, ttl))
        return data

    async def post_json(self, url: str, payload: dict, headers: dict | None = None) -> dict:
        # POST не кэшируется — мутация по определению
        _validate_external_url(url)
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers or {}, follow_redirects=False)
            resp.raise_for_status()
        duration_ms = int((time.monotonic() - start) * 1000)
        _log.info(f"http POST {url} status={resp.status_code} duration_ms={duration_ms}")
        return resp.json()
```

## [S5] SSRF-защита

`orchestrator/api/connectors.py:185` (`_validate_external_url`) уже
реализует нужную проверку (IP-литерал + DNS resolve, блокировка RFC 1918/
loopback/link-local/multicast/reserved), но поднимает `HTTPException` —
FastAPI-специфичный класс, недоступный в `soar/` (subprocess-раннер не
зависит от `orchestrator`, по архитектуре зависимость только в одну
сторону). `soar/tools/http_client.py` реализует ту же логику отдельной
функцией `_validate_external_url(url: str) -> None`, поднимающей
`ValueError`, а не дублирует существующую как есть — это осознанное
дублирование через границу процессов, не лишний код.

**Почему это нужно именно здесь, не только в orchestrator:** некоторые
threat-intel actions строят URL из данных алерта (например, проверка URL
из IOC через urlhaus/VT) — то есть входные данные частично
атакер-контролируемы, а не всегда захардкоженный домен API. Без этой
проверки `HttpClient`, вызванный с IOC-URL, может быть использован для
SSRF во внутреннюю сеть/cloud metadata endpoint из-под worker-процесса.

## [S6] Конфиг

```yaml
# config.yaml
http_client:
  cache_backend: memory   # memory | redis | none
  default_ttl: 3600
  domain_ttl:
    api.virustotal.com: 86400
    api.abusech.org: 3600
    api.kaspersky.com: 43200
```

```python
# orchestrator/config.py
class HttpClientConfig(BaseModel):
    cache_backend: str = "memory"   # memory | redis | none
    default_ttl: int = 3600
    domain_ttl: dict[str, int] = {}

class OrchestratorConfig(BaseModel):
    ...
    http_client: HttpClientConfig = HttpClientConfig()
```

`cache_backend: none` → `HttpClient(cache=None, ...)` — чистое
логирование, `cached=True` на вызовах становится no-op. `redis` — переиспользует
`queue.redis_url`, отдельное поле не заводим (то же соединение, тот же
Redis-инстанс, что и очередь, если он есть; при `cache_backend: redis` и
пустом `queue.redis_url` — ошибка конфигурации при старте, не тихий
fallback на memory).

`soar/runner.py` читает `SOAR_CONFIG` (как уже делает для остального
конфига) и инициализирует `soar.tools.http_client` singleton тем же
образом, что уже написано в `[S6]` v0.6-спеки — этот кусок конфигурации
переносится сюда без изменений.

## [S7] Использование в actions

```python
from soar.tools import http_client

async def vt_check_ip(ip: str) -> dict:
    return await http_client.get_json(
        f"https://api.virustotal.com/api/v3/ip_addresses/{ip}",
        headers={"x-apikey": _api_key()},
    )
```

Точечный вызов с обходом кэша (например, известно, что данные устарели):

```python
await http_client.get_json(url, ttl=60, cached=False)
```

## [S8] Testing Strategy

- `InMemoryCache`: тест TTL expiry (`time.monotonic` через monkeypatch).
- `HttpClient.get_json`: mock `httpx.AsyncClient` — тест cache-hit (второй
  вызов не делает реальный HTTP-запрос при `cache` заданном); тест что
  `cached=False` всегда идёт в сеть, даже с горячим кэшем; тест что без
  `cache` бэкенда (`cache=None`) `cached=True` не ломает вызов (no-op).
- `post_json`: тест что кэш никогда не используется, даже если `cache` задан.
- `_validate_external_url`: тест на блокировку RFC1918/loopback/link-local
  IP-литералов и на резолвящиеся в них домены (тот же набор кейсов, что
  уже покрыт для `orchestrator/api/connectors.py::_validate_external_url`,
  дублируется на этот модуль).
- Логирование: тест что `get_json`/`post_json` каждый вызывают `_log.info`
  ровно один раз на запрос (через `loguru` sink capture), и `_log.debug`
  на cache-hit.
- `RedisCache`: тест на моке `redis.from_url` — не требует реального Redis.

## [S9] Non-goals

- Миграция существующих 10 threat-intel коннекторов на `HttpClient` вместо
  прямых `httpx`/`requests` вызовов — отдельная задача после того, как
  этот примитив появится и будет обкатан; не блокирует появление самого
  инструмента.
- Per-workflow метрики и dry-run конвенция — Feature 2/3 v0.6-спеки, не
  входят в эту спеку.

## [S10] Success Criteria

- [ ] `HttpClient` singleton доступен как `soar.tools.http_client`
- [ ] `get_json`/`post_json` логируют каждый запрос через loguru
      безусловно, независимо от наличия кэш-бэкенда
- [ ] С `cache_backend: none` — `cached=True` не ломает вызовы, просто не
      кэширует (проверено тестом)
- [ ] Второй вызов `get_json` с тем же url+headers и `cached=True` не
      делает реальный HTTP-запрос при заданном кэш-бэкенде
- [ ] `post_json` никогда не кэшируется
- [ ] `_validate_external_url` блокирует RFC1918/loopback/link-local/
      metadata-адреса и их DNS-резолвинг
- [ ] Конфиг `http_client` с дефолтами не ломает существующие деплои
      (дефолт `cache_backend: memory`, работает без Redis)
- [ ] Все существующие тесты проходят
