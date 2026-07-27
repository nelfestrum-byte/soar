"""Shared HTTP client for threat-intel connector actions.

Logging is unconditional (one loguru call per request: method, domain,
status, duration_ms, cache_hit) — same "one log line per request"
philosophy as `access_log_middleware` in `orchestrator/main.py`, mirrored
here for the soar-action HTTP layer. Caching is optional, pluggable via
`CacheBackend`, and never applies to POST (mutation by definition).

`_validate_external_url` reimplements the SSRF guard from
`orchestrator/api/connectors.py::_validate_external_url` rather than
importing it: `soar/` must not depend on `orchestrator/` (subprocess
runner boundary, one-way dependency), and it needs to raise `ValueError`
instead of the FastAPI-specific `HTTPException`.
"""

import hashlib
import ipaddress
import socket
import time
from typing import Protocol
from urllib.parse import urlparse

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


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        return False


def _validate_external_url(url: str) -> None:
    """Block requests to internal/private IP ranges, including via DNS."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only HTTP/HTTPS URLs allowed")
    hostname = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None

    if ip is not None:
        # Direct IP literal: check immediately
        if _is_private_ip(str(ip)):
            raise ValueError("Requests to internal IPs are not allowed")
        return

    # Resolve hostname and check each returned address
    try:
        results = socket.getaddrinfo(hostname, None)
    except OSError as e:
        raise ValueError("Could not resolve hostname") from e
    for result in results:
        addr_ip = result[4][0]
        if _is_private_ip(addr_ip):
            raise ValueError("Requests to internal IPs are not allowed")


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
