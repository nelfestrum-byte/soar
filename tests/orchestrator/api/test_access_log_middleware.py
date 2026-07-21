import time

import pytest
from httpx import ASGITransport, AsyncClient
from loguru import logger

from orchestrator.main import app, rate_limiter


@pytest.fixture
def log_records():
    records = []

    def sink(message):
        records.append(message.record)

    handler_id = logger.add(sink, level="DEBUG")
    yield records
    logger.remove(handler_id)


async def test_access_log_middleware_sets_request_id_header(setup_app_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) == 16


async def test_access_log_middleware_uses_distinct_request_ids(setup_app_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/status")
        r2 = await client.get("/status")

    assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]


async def test_access_log_middleware_wraps_rate_limited_response(setup_app_state):
    """Access-log middleware must be the outermost layer — it should still tag
    a 429 raised by rate_limit_middleware with X-Request-ID. Mirrors the
    trusted-proxy setup from test_rate_limiter.py to force an actual 429
    (ASGITransport's client_ip is 127.0.0.1, which is otherwise skip-listed)."""
    from orchestrator.main import app as _app

    _app.state.config.server.trusted_proxies = ["127.0.0.1"]
    now = time.monotonic()
    rate_limiter._requests["9.9.9.9"] = [now] * rate_limiter._max

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status", headers={"X-Real-IP": "9.9.9.9"})

    rate_limiter._requests.pop("9.9.9.9", None)

    assert response.status_code == 429
    assert "X-Request-ID" in response.headers


async def test_access_log_middleware_logs_request_metadata(setup_app_state, log_records):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/status")

    access_records = [r for r in log_records if r["message"] == "request"]
    assert len(access_records) == 1
    extra = access_records[0]["extra"]
    assert extra["method"] == "GET"
    assert extra["path"] == "/status"
    assert extra["status"] == 200
    assert isinstance(extra["duration_ms"], float)
    assert "request_id" in extra
