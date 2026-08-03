from unittest.mock import patch

import httpx
import pytest
from loguru import logger

from soar.tools._cache import InMemoryCache, RedisCache
from soar.tools.http_client import CachingHttpClient, LoggingHttpClient


@pytest.fixture
def log_records():
    records = []

    def sink(message):
        records.append(message.record)

    handler_id = logger.add(sink, level="DEBUG")
    yield records
    logger.remove(handler_id)


def _response(request: httpx.Request, status_code: int = 200, content: bytes = b'{"result": "ok"}') -> httpx.Response:
    return httpx.Response(status_code, content=content, request=request)


def _make_addrinfo(ip: str):
    import socket
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80))]


# --- InMemoryCache / RedisCache (moved to _cache.py, no behavior change) ---


def test_in_memory_cache_roundtrip():
    cache = InMemoryCache()
    cache.set("k", {"v": 1}, ttl=60)
    assert cache.get("k") == {"v": 1}


def test_redis_cache_get_set_uses_mocked_client():
    with patch("redis.from_url") as mock_from_url:
        mock_client = mock_from_url.return_value
        mock_client.get.return_value = '{"v": 1}'
        cache = RedisCache("redis://localhost:6379/0")
        assert cache.get("abc123") == {"v": 1}
        cache.set("abc123", {"v": 2}, ttl=60)
        mock_client.setex.assert_called_once_with("soar:httpcache:abc123", 60, '{"v": 2}')


# --- LoggingHttpClient ---


def test_logging_client_logs_once_per_successful_request(log_records):
    client = LoggingHttpClient()
    with patch("httpx.Client.send", return_value=_response(httpx.Request("GET", "https://api.example.com/x"))) as mock_send, \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        resp = client.get("https://api.example.com/x")

    assert resp.json() == {"result": "ok"}
    mock_send.assert_called_once()
    info_records = [r for r in log_records if r["level"].name == "INFO"]
    assert len(info_records) == 1
    assert "GET" in info_records[0]["message"]


def test_logging_client_logs_before_raising_on_error_status(log_records):
    client = LoggingHttpClient()
    error_response = _response(httpx.Request("GET", "https://api.example.com/x"), status_code=500, content=b"boom")
    with patch("httpx.Client.send", return_value=error_response), \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        with pytest.raises(httpx.HTTPStatusError):
            client.get("https://api.example.com/x")

    info_records = [r for r in log_records if r["level"].name == "INFO"]
    assert len(info_records) == 1
    assert "status=500" in info_records[0]["message"]


def test_logging_client_ssrf_guard_blocks_before_network_call():
    client = LoggingHttpClient()
    with patch("httpx.Client.send") as mock_send:
        with pytest.raises(ValueError):
            client.get("http://10.0.0.1/x")
    mock_send.assert_not_called()


def test_logging_client_redacts_query_string_in_logs(log_records):
    client = LoggingHttpClient()
    url = "https://api.example.com/x?apikey=SUPERSECRET"
    with patch("httpx.Client.send", return_value=_response(httpx.Request("GET", url))), \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        client.get(url)

    info_records = [r for r in log_records if r["level"].name == "INFO"]
    assert "SUPERSECRET" not in info_records[0]["message"]
    assert "apikey" not in info_records[0]["message"]


def test_logging_client_defaults_timeout_and_no_redirects():
    client = LoggingHttpClient()
    assert client.follow_redirects is False
    assert client.timeout == httpx.Timeout(30)


def test_logging_client_verify_held_on_instance():
    with patch.object(httpx.Client, "__init__", return_value=None) as mock_init:
        LoggingHttpClient(verify=False)
    _, kwargs = mock_init.call_args
    assert kwargs["verify"] is False


# --- CachingHttpClient ---


def test_caching_client_without_cache_behaves_like_logging_client():
    client = CachingHttpClient(cache=None)
    with patch("httpx.Client.send", return_value=_response(httpx.Request("GET", "https://api.example.com/x"))) as mock_send, \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        client.get("https://api.example.com/x")
        client.get("https://api.example.com/x")

    assert mock_send.call_count == 2


def test_caching_client_second_get_is_cache_hit(log_records):
    client = CachingHttpClient(cache=InMemoryCache())
    url = "https://api.example.com/x"
    with patch("httpx.Client.send", return_value=_response(httpx.Request("GET", url))) as mock_send, \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        first = client.get(url)
        second = client.get(url)

    assert first.json() == second.json() == {"result": "ok"}
    mock_send.assert_called_once()
    debug_records = [r for r in log_records if r["level"].name == "DEBUG"]
    assert len(debug_records) == 1


def test_caching_client_only_caches_successful_responses():
    cache = InMemoryCache()
    client = CachingHttpClient(cache=cache)
    url = "https://api.example.com/x"
    error_response = _response(httpx.Request("GET", url), status_code=500, content=b"boom")
    with patch("httpx.Client.send", return_value=error_response), \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        with pytest.raises(httpx.HTTPStatusError):
            client.get(url)

    from soar.tools.http_client import _cache_key
    assert cache.get(_cache_key(url, {})) is None


def test_caching_client_never_caches_post(log_records):
    client = CachingHttpClient(cache=InMemoryCache())
    url = "https://api.example.com/submit"
    with patch("httpx.Client.send", return_value=_response(httpx.Request("POST", url), content=b'{"created": true}')) as mock_send, \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        client.post(url, json={"a": 1})
        client.post(url, json={"a": 1})

    assert mock_send.call_count == 2
    info_records = [r for r in log_records if r["level"].name == "INFO"]
    assert len(info_records) == 2
    assert all("POST" in r["message"] for r in info_records)


def test_caching_client_never_caches_put():
    client = CachingHttpClient(cache=InMemoryCache())
    url = "https://api.example.com/agents/1/restart"
    with patch("httpx.Client.send", return_value=_response(httpx.Request("PUT", url), content=b'{"updated": true}')) as mock_send, \
            patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        client.put(url)
        client.put(url)

    assert mock_send.call_count == 2
