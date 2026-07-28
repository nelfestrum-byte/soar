from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.config import OrchestratorConfig
from orchestrator.core.job_manager import JobManager
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.main import app
from orchestrator.models import ConcurrencyPolicy
from orchestrator.models.workflow_meta import WorkflowMeta
from orchestrator.store.job_store import JobStore


@pytest.fixture(autouse=True)
def setup_webhook_app():
    queue = InMemoryQueue()
    job_store = JobStore()
    runner = SubprocessRunner()
    git = MagicMock()
    config = OrchestratorConfig()

    job_manager = JobManager(
        queue=queue, job_store=job_store, runner=runner, log_dir="/tmp/test",
    )
    meta = WorkflowMeta(
        name="TestWebhook", type="webhook", enabled=True,
        path="/webhook/test", token="secret-token-abc",
        concurrency=ConcurrencyPolicy.ALLOW,
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
async def test_webhook_valid_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/TestWebhook",
            json={"data": "test"},
            headers={"X-Webhook-Token": "secret-token-abc"},
        )
        assert resp.status_code == 202
        assert "job_id" in resp.json()


@pytest.mark.asyncio
async def test_webhook_wrong_token():
    async with app.state.db_session_factory() as session:
        before = len(list((await session.execute(select(AuditLog))).scalars()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/TestWebhook",
            json={},
            headers={"X-Webhook-Token": "wrong"},
        )
        assert resp.status_code == 403

    async with app.state.db_session_factory() as session:
        after = len(list((await session.execute(select(AuditLog))).scalars()))
    assert after == before


@pytest.mark.asyncio
async def test_webhook_missing_token():
    async with app.state.db_session_factory() as session:
        before = len(list((await session.execute(select(AuditLog))).scalars()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/webhooks/TestWebhook", json={})
        assert resp.status_code == 403

    async with app.state.db_session_factory() as session:
        after = len(list((await session.execute(select(AuditLog))).scalars()))
    assert after == before


@pytest.mark.asyncio
async def test_webhook_disabled_workflow():
    app.state.job_manager._metas["TestWebhook"].enabled = False

    async with app.state.db_session_factory() as session:
        before = len(list((await session.execute(select(AuditLog))).scalars()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/TestWebhook",
            json={},
            headers={"X-Webhook-Token": "secret-token-abc"},
        )
        assert resp.status_code == 409

    async with app.state.db_session_factory() as session:
        after = len(list((await session.execute(select(AuditLog))).scalars()))
    assert after == before
    app.state.job_manager._metas["TestWebhook"].enabled = True


@pytest.mark.asyncio
async def test_webhook_not_webhook_type():
    meta = WorkflowMeta(name="ScheduledOne", type="scheduled", enabled=True)
    app.state.job_manager._metas["ScheduledOne"] = meta
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/webhooks/ScheduledOne", json={})
        assert resp.status_code == 404
    del app.state.job_manager._metas["ScheduledOne"]
