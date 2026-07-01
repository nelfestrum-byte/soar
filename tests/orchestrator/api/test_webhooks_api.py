import pytest
from httpx import ASGITransport, AsyncClient

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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/webhooks/disabled_wh",
            json={"test": 1},
            headers={"X-Webhook-Token": "validtoken"},
        )
        assert r.status_code == 409
