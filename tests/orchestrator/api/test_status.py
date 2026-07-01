from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.config import OrchestratorConfig
from orchestrator.core.job_manager import JobManager
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.main import app
from orchestrator.store.job_store import JobStore


@pytest.fixture(autouse=True)
def setup_app_state():
    queue = InMemoryQueue()
    job_store = JobStore()
    runner = SubprocessRunner()
    git = MagicMock()
    config = OrchestratorConfig()

    job_manager = JobManager(
        queue=queue,
        job_store=job_store,
        runner=runner,
        log_dir="/tmp/test_logs",
    )
    job_manager.set_metas([])

    pool = WorkerPool(
        count=2, queue=queue, runner=runner,
        job_store=job_store, default_timeout=300,
    )
    scheduler = OrchestratorScheduler(job_manager)

    app.state.job_manager = job_manager
    app.state.pool = pool
    app.state.scheduler = scheduler
    app.state.git = git
    app.state.config = config
    app.state.job_store = job_store
    app.state.queue = queue


@pytest.mark.asyncio
async def test_status_redis_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert "queue" in data
        assert "backend" in data["queue"]
        # For memory backend, connected field should not be present
        # For redis backend, connected field should be present
        if data["queue"]["backend"] == "redis":
            assert "connected" in data["queue"]
