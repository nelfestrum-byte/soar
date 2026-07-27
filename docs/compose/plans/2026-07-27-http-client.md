# Plan: HTTP Client Tool (Logging + Optional Caching)

Spec: `docs/compose/specs/2026-07-27-http-client-design.md`

## Tests first (`tests/soar/tools/test_http_client.py`)

- [x] `InMemoryCache`: set/get roundtrip
- [x] `InMemoryCache`: TTL expiry via `time.monotonic` monkeypatch (entry gone after expiry)
- [x] `RedisCache`: `get`/`set` against a mocked `redis.from_url` client, no real Redis needed
- [x] `_validate_external_url`: blocks direct private/loopback/link-local IP literals
- [x] `_validate_external_url`: blocks domains resolving (via mocked `socket.getaddrinfo`) to private/metadata IPs
- [x] `_validate_external_url`: allows domains resolving to public IPs
- [x] `_validate_external_url`: rejects non-http(s) schemes
- [x] `_validate_external_url`: raises `ValueError` (not `HTTPException` — soar/ can't depend on orchestrator/)
- [x] `HttpClient.get_json`: mocked `httpx.AsyncClient`, first call hits network, `_log.info` fired once
- [x] `HttpClient.get_json`: second call with same url+headers and `cached=True` + cache backend set is a cache hit — no second network call, `_log.debug` fired
- [x] `HttpClient.get_json`: `cached=False` always goes to network even with a hot cache entry
- [x] `HttpClient.get_json`: with `cache=None`, `cached=True` is a no-op (doesn't raise, doesn't crash)
- [x] `HttpClient.get_json`: calls `_validate_external_url` (SSRF guard applied before request)
- [x] `HttpClient.post_json`: never uses the cache even when a cache backend is configured, `_log.info` fired once
- [x] `HttpClient.post_json`: calls `_validate_external_url`
- [x] Confirm tests fail before implementation exists (`ModuleNotFoundError: soar.tools.http_client`)

## Implementation

- [x] `soar/tools/http_client.py` — `CacheBackend` protocol, `InMemoryCache`, `RedisCache`, `HttpClient`, `_validate_external_url`, `_is_private_ip` (per spec [S4]/[S5], copied SSRF logic from `orchestrator/api/connectors.py:185` but raising `ValueError`)
- [x] `soar/tools/__init__.py` — export `http_client` as a module-level `HttpClient()` singleton instance (default: no cache backend, pure logging-proxy) so `from soar.tools import http_client; await http_client.get_json(...)` works out of the box before `runner.py` reconfigures it
- [x] `orchestrator/config.py` — `HttpClientConfig` model (`cache_backend: str = "memory"`, `default_ttl: int = 3600`, `domain_ttl: dict[str, int] = {}`), `OrchestratorConfig.http_client` field
- [x] `soar/runner.py` — read `http_client` section from the same `SOAR_CONFIG` yaml already loaded, build the right `CacheBackend` (`memory` → `InMemoryCache()`, `redis` → `RedisCache(queue.redis_url)` erroring if `queue.redis_url` empty, `none`/unknown-safe → `None`), reassign the `soar.tools` package's `http_client` singleton with real config values

## Verification

- [x] Run new test file alone, all green
- [x] Run full suite `python -m pytest`, all green (601 existing + new)
- [x] Write report `docs/compose/reports/http-client.md`
