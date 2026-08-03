"""Internal cache backends for soar/tools/http_client.py — not part of the
public tool surface (soar/tools/__init__.py::TOOL_REGISTRY), per the
`_*.py` internal-mechanics convention (CLAUDE.md, docs/compose/specs/
2026-08-03-tools-redesign-design.md [S2](b))."""

import time
from typing import Protocol


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
