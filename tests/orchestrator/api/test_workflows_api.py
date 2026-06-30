import pytest
from unittest.mock import MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport
from orchestrator.main import app
from orchestrator.config import OrchestratorConfig
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.job_manager import JobManager
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.store.job_store import JobStore
from orchestrator.models.workflow_meta import WorkflowMeta
from orchestrator.models import ConcurrencyPolicy


@pytest.fixture(autouse=True)
def setup_workflows_app():
    queue = InMemoryQueue()
    job_store = JobStore()
    runner = SubprocessRunner()
    git = MagicMock()
    config = OrchestratorConfig()

    job_manager = JobManager(
        queue=queue, job_store=job_store, runner=runner, log_dir="/tmp/test",
    )
    meta = WorkflowMeta(
        name="MyWorkflow", type="scheduled", enabled=True,
        schedule="*/10 * * * *", concurrency=ConcurrencyPolicy.FORBID,
    )
    job_manager.set_metas([meta])

    pool = WorkerPool(count=1, queue=queue, runner=runner, job_store=job_store, default_timeout=300)
    scheduler = OrchestratorScheduler(job_manager)

    app.state.job_manager = job_manager
    app.state.pool = pool
    app.state.scheduler = scheduler
    app.state.git = git
    app.state.config = config
    app.state.job_store = job_store
    app.state.queue = queue


@pytest.mark.asyncio
async def test_list_workflows_no_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "MyWorkflow"
        assert "token" not in data[0]


@pytest.mark.asyncio
async def test_get_workflow_detail():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/workflows/MyWorkflow")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "MyWorkflow"
        assert data["enabled"] is True
        assert "token" not in data


@pytest.mark.asyncio
async def test_enable_disable_workflow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/workflows/MyWorkflow/disable")
        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"

        resp = await client.get("/workflows/MyWorkflow")
        assert resp.json()["enabled"] is False

        resp = await client.post("/workflows/MyWorkflow/enable")
        assert resp.status_code == 200
        assert resp.json()["status"] == "enabled"

        resp = await client.get("/workflows/MyWorkflow")
        assert resp.json()["enabled"] is True


@pytest.mark.asyncio
async def test_reload_workflows():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/workflows/reload")
        assert resp.status_code == 200
        assert "count" in resp.json()
