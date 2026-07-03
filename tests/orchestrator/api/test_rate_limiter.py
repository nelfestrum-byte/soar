"""B5: rate limiter should use X-Real-IP when client is a trusted proxy."""
import time
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock

from orchestrator.config import OrchestratorConfig, ServerConfig
from orchestrator.core.job_manager import JobManager
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.main import app, RateLimiter
from orchestrator.store.job_store import JobStore


def _setup_state(trusted_proxies: list[str]):
    queue = InMemoryQueue()
    job_store = JobStore()
    runner = SubprocessRunner()
    config = OrchestratorConfig(server=ServerConfig(trusted_proxies=trusted_proxies))
    job_manager = JobManager(queue=queue, job_store=job_store, runner=runner, log_dir="/tmp")
    job_manager.set_metas([])
    pool = WorkerPool(count=1, queue=queue, runner=runner, job_store=job_store, default_timeout=30)
    scheduler = OrchestratorScheduler(job_manager)

    app.state.job_manager = job_manager
    app.state.pool = pool
    app.state.scheduler = scheduler
    app.state.git = MagicMock()
    app.state.config = config
    app.state.job_store = job_store
    app.state.queue = queue


@pytest.mark.asyncio
async def test_rate_limit_uses_forwarded_ip_when_trusted_proxy():
    """B5: X-Real-IP is used for rate limiting when client is a trusted proxy.

    httpx ASGITransport sets request.client.host = "127.0.0.1", so we configure
    "127.0.0.1" as a trusted proxy. The middleware must then use X-Real-IP for
    rate limiting instead of skipping (127.0.0.1 is in the default skip list).
    """
    _setup_state(trusted_proxies=["127.0.0.1"])

    # Fill the rate limiter bucket for the forwarded IP with recent timestamps
    from orchestrator.main import rate_limiter
    now = time.monotonic()
    rate_limiter._requests["9.9.9.9"] = [now] * rate_limiter._max

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status", headers={"X-Real-IP": "9.9.9.9"})
        assert response.status_code == 429

    # Cleanup
    rate_limiter._requests.pop("9.9.9.9", None)


@pytest.mark.asyncio
async def test_rate_limit_ignores_forwarded_ip_without_trusted_proxy():
    """B5: X-Real-IP must be ignored when no trusted proxies are configured.

    Even if X-Real-IP is set, the middleware must use client_ip ("127.0.0.1"),
    which is in the skip list — so the request passes through.
    """
    _setup_state(trusted_proxies=[])

    from orchestrator.main import rate_limiter
    # Fill bucket for 9.9.9.9; should have NO effect because we're ignoring X-Real-IP
    now = time.monotonic()
    rate_limiter._requests["9.9.9.9"] = [now] * rate_limiter._max

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 127.0.0.1 → not in trusted_proxies → X-Real-IP ignored → falls to skip list → 200
        response = await client.get("/status", headers={"X-Real-IP": "9.9.9.9"})
        assert response.status_code == 200

    rate_limiter._requests.pop("9.9.9.9", None)
