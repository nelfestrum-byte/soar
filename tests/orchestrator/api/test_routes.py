import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from orchestrator.main import app
from orchestrator.config import OrchestratorConfig
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.job_manager import JobManager
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.git_manager import GitManager
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
async def test_status_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert "workers" in data
        assert "queue" in data
        assert "jobs" in data
        assert "scheduler" in data


@pytest.mark.asyncio
async def test_list_workflows():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/workflows")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_workflow_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/workflows/NonExistent")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_job_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/jobs", json={
            "workflow_name": "NonExistent",
            "context": {},
        })
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_jobs():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/jobs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_job_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/jobs/nonexistent")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_files():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/files")
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


@pytest.mark.asyncio
async def test_webhook_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/webhooks/nonexistent", json={})
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_webhook_invalid_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/nonexistent",
            json={},
            headers={"X-Webhook-Token": "wrong"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_logs_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/logs/nonexistent")
        assert response.status_code == 404
