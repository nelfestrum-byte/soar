"""Shared HTTP client for threat-intel connector actions.

Logging is unconditional (one loguru call per request: method, domain,
status, duration_ms, cache_hit) — same "one log line per request"
philosophy as `access_log_middleware` in `orchestrator/main.py`, mirrored
here for the soar-action HTTP layer. Caching is optional, pluggable via
`CacheBackend`, and never applies to POST/PUT/DELETE (mutation by
definition).

`LoggingHttpClient`/`CachingHttpClient` subclass `httpx.Client` directly
(override `send()`) instead of wrapping `get_json`/`post_json`/`put_json`
by hand — one override point covers every httpx method (`get`/`post`/
`put`/`delete`/`head`/...) and every response shape (`.json()` for JSON
APIs, `.content` for binary responses like pcap), not just JSON (docs/
compose/specs/2026-08-03-tools-redesign-design.md [S1]/[S2](c)).

`_validate_external_url` (soar/tools/_net.py) reimplements the SSRF guard
from `orchestrator/api/connectors.py::_validate_external_url` rather than
importing it: `soar/` must not depend on `orchestrator/` (subprocess
runner boundary, one-way dependency), and it needs to raise `ValueError`
instead of the FastAPI-specific `HTTPException`.
"""

import hashlib
import time

import httpx
from loguru import logger as _log

from soar.tools._cache import CacheBackend
from soar.tools._net import _log_safe_url, _validate_external_url


def _cache_key(url: str, headers: dict) -> str:
    raw = url + str(sorted(headers.items()))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _ttl_for(domain_ttl: dict[str, int], default_ttl: int, url: str, ttl: int | None) -> int:
    if ttl is not None:
        return ttl
    domain = httpx.URL(url).host
    return domain_ttl.get(domain, default_ttl)


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
        response.raise_for_status()  # тот же контракт, что get_json/post_json дают сегодня
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


# Filled in by soar/runner.py at process start, same shared cache/ttl config
# as the tools.http_client singleton — see new_client() below.
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
