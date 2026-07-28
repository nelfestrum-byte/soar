import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.main import app


@pytest.mark.asyncio
async def test_webhook_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/webhooks/nonexistent", json={})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_invalid_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/webhooks/nonexistent",
            json={},
            headers={"X-Webhook-Token": "wrong"},
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_not_webhook_type():
    from orchestrator.models.workflow_meta import WorkflowMeta
    from orchestrator.models import ConcurrencyPolicy

    meta = WorkflowMeta(
        name="manual_wf",
        type="manual",
        enabled=True,
        path="manual_wf",
        timeout=300,
        concurrency=ConcurrencyPolicy.FORBID,
    )
    app.state.job_manager.set_metas([meta])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/webhooks/manual_wf", json={})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_disabled():
    from orchestrator.models.workflow_meta import WorkflowMeta
    from orchestrator.models import ConcurrencyPolicy

    meta = WorkflowMeta(
        name="disabled_wh",
        type="webhook",
        enabled=False,
        path="disabled_wh",
        token="validtoken",
        timeout=300,
        concurrency=ConcurrencyPolicy.FORBID,
    )
    app.state.job_manager.set_metas([meta])

    async with app.state.db_session_factory() as session:
        before = len(list((await session.execute(select(AuditLog))).scalars()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/webhooks/disabled_wh",
            json={"test": 1},
            headers={"X-Webhook-Token": "validtoken"},
        )
        assert r.status_code == 409

    async with app.state.db_session_factory() as session:
        after = len(list((await session.execute(select(AuditLog))).scalars()))
    assert after == before


@pytest.mark.asyncio
async def test_webhook_success_writes_audit_log():
    from orchestrator.models.workflow_meta import WorkflowMeta
    from orchestrator.models import ConcurrencyPolicy

    meta = WorkflowMeta(
        name="audited_wh",
        type="webhook",
        enabled=True,
        path="audited_wh",
        token="validtoken",
        timeout=300,
        concurrency=ConcurrencyPolicy.ALLOW,
    )
    app.state.job_manager.set_metas([meta])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/webhooks/audited_wh",
            json={"secret": "should-not-be-in-audit-log"},
            headers={"X-Webhook-Token": "validtoken"},
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]

    async with app.state.db_session_factory() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.resource_type == "job", AuditLog.resource_id == job_id)
        )
        rows = list(result.scalars())
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "job.create"
    assert row.actor_type == "webhook"
    assert row.actor_name == "webhook:audited_wh"
    assert row.detail == {"workflow_name": "audited_wh", "triggered_by": "webhook"}
