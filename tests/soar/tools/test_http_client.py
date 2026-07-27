import socket
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger

from soar.tools.http_client import (
    HttpClient,
    InMemoryCache,
    RedisCache,
    _validate_external_url,
)


@pytest.fixture
def log_records():
    records = []

    def sink(message):
        records.append(message.record)

    handler_id = logger.add(sink, level="DEBUG")
    yield records
    logger.remove(handler_id)


def _make_addrinfo(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80))]


def _mock_async_client(json_data=None, status_code=200):
    """Build a mock that stands in for `httpx.AsyncClient() as client`."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)

    ctx = AsyncMock()
    ctx.__aenter__.return_value = client
    ctx.__aexit__.return_value = False
    return ctx, client


# --- InMemoryCache ---


def test_in_memory_cache_roundtrip():
    cache = InMemoryCache()
    cache.set("k", {"v": 1}, ttl=60)
    assert cache.get("k") == {"v": 1}


def test_in_memory_cache_missing_key():
    cache = InMemoryCache()
    assert cache.get("missing") is None


def test_in_memory_cache_ttl_expiry(monkeypatch):
    cache = InMemoryCache()
    fake_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])

    cache.set("k", {"v": 1}, ttl=10)
    assert cache.get("k") == {"v": 1}

    fake_time[0] = 1011.0
    assert cache.get("k") is None
    assert "k" not in cache._store


# --- RedisCache ---


def test_redis_cache_get_set_uses_mocked_client():
    with patch("redis.from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_from_url.return_value = mock_client
        mock_client.get.return_value = '{"v": 1}'

        cache = RedisCache("redis://localhost:6379/0")
        mock_from_url.assert_called_once_with("redis://localhost:6379/0")

        result = cache.get("abc123")
        mock_client.get.assert_called_once_with("soar:httpcache:abc123")
        assert result == {"v": 1}

        cache.set("abc123", {"v": 2}, ttl=60)
        mock_client.setex.assert_called_once_with("soar:httpcache:abc123", 60, '{"v": 2}')


def test_redis_cache_get_miss_returns_none():
    with patch("redis.from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_from_url.return_value = mock_client
        mock_client.get.return_value = None

        cache = RedisCache("redis://localhost:6379/0")
        assert cache.get("missing") is None


# --- _validate_external_url ---


def test_validate_external_url_blocks_direct_private_ip():
    with pytest.raises(ValueError):
        _validate_external_url("http://10.0.0.1/x")


def test_validate_external_url_blocks_loopback():
    with pytest.raises(ValueError):
        _validate_external_url("http://127.0.0.1/x")


def test_validate_external_url_blocks_domain_resolving_to_private():
    with patch("socket.getaddrinfo", return_value=_make_addrinfo("10.0.0.1")):
        with pytest.raises(ValueError):
            _validate_external_url("http://internal.example.com/x")


def test_validate_external_url_blocks_domain_resolving_to_metadata():
    with patch("socket.getaddrinfo", return_value=_make_addrinfo("169.254.169.254")):
        with pytest.raises(ValueError):
            _validate_external_url("http://metadata.google.internal/x")


def test_validate_external_url_allows_public_domain():
    with patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        _validate_external_url("http://public.example.com/x")  # should not raise


def test_validate_external_url_blocks_non_http_scheme():
    with pytest.raises(ValueError):
        _validate_external_url("ftp://example.com/x")


# --- HttpClient.get_json ---


async def test_get_json_hits_network_and_logs(log_records):
    client_ctx, client = _mock_async_client({"result": "ok"})
    http_client = HttpClient(cache=InMemoryCache())

    with patch("soar.tools.http_client.httpx.AsyncClient", return_value=client_ctx), \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        data = await http_client.get_json("https://api.example.com/v1/ip/1.2.3.4")

    assert data == {"result": "ok"}
    client.get.assert_called_once()
    info_records = [r for r in log_records if r["level"].name == "INFO"]
    assert len(info_records) == 1
    assert "GET" in info_records[0]["message"]


async def test_get_json_second_call_is_cache_hit(log_records):
    client_ctx, client = _mock_async_client({"result": "ok"})
    http_client = HttpClient(cache=InMemoryCache())
    url = "https://api.example.com/v1/ip/1.2.3.4"

    with patch("soar.tools.http_client.httpx.AsyncClient", return_value=client_ctx), \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        first = await http_client.get_json(url)
        second = await http_client.get_json(url)

    assert first == second == {"result": "ok"}
    client.get.assert_called_once()  # only one real network call
    debug_records = [r for r in log_records if r["level"].name == "DEBUG"]
    assert len(debug_records) == 1


async def test_get_json_cached_false_always_hits_network():
    client_ctx, client = _mock_async_client({"result": "ok"})
    http_client = HttpClient(cache=InMemoryCache())
    url = "https://api.example.com/v1/ip/1.2.3.4"

    with patch("soar.tools.http_client.httpx.AsyncClient", return_value=client_ctx), \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        await http_client.get_json(url, cached=False)
        await http_client.get_json(url, cached=False)

    assert client.get.call_count == 2


async def test_get_json_without_cache_backend_cached_true_is_noop():
    client_ctx, client = _mock_async_client({"result": "ok"})
    http_client = HttpClient(cache=None)
    url = "https://api.example.com/v1/ip/1.2.3.4"

    with patch("soar.tools.http_client.httpx.AsyncClient", return_value=client_ctx), \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        await http_client.get_json(url, cached=True)
        await http_client.get_json(url, cached=True)

    assert client.get.call_count == 2  # no cache backend, nothing to hit


async def test_get_json_validates_url_before_request():
    http_client = HttpClient()
    with pytest.raises(ValueError):
        await http_client.get_json("http://10.0.0.1/x")


# --- HttpClient.post_json ---


async def test_post_json_never_cached(log_records):
    client_ctx, client = _mock_async_client({"created": True})
    http_client = HttpClient(cache=InMemoryCache())
    url = "https://api.example.com/v1/submit"

    with patch("soar.tools.http_client.httpx.AsyncClient", return_value=client_ctx), \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        await http_client.post_json(url, {"a": 1})
        await http_client.post_json(url, {"a": 1})

    assert client.post.call_count == 2
    info_records = [r for r in log_records if r["level"].name == "INFO"]
    assert len(info_records) == 2
    assert all("POST" in r["message"] for r in info_records)


async def test_post_json_validates_url_before_request():
    http_client = HttpClient()
    with pytest.raises(ValueError):
        await http_client.post_json("http://127.0.0.1/x", {"a": 1})
