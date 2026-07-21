import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.main import app


async def _audit_rows(resource_type: str, resource_id: str) -> list[AuditLog]:
    async with app.state.db_session_factory() as session:
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id
            )
        )
        return list(result.scalars())


@pytest.mark.asyncio
async def test_list_workflows_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_get_workflow_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_enable_workflow_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/workflows/nonexistent/enable")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_disable_workflow_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/workflows/nonexistent/disable")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_reload_workflows():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/workflows/reload")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "reloaded"
        assert "count" in data


@pytest.mark.asyncio
async def test_reload_scheduler():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/workflows/scheduler/reload")
        assert r.status_code == 200
        assert r.json()["status"] == "reloaded"


@pytest.mark.asyncio
async def test_workflow_template():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/code/template")
        assert r.status_code == 200
        assert "content" in r.json()


@pytest.mark.asyncio
async def test_workflow_template_types():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for wf_type in ["scheduled", "webhook", "manual"]:
            r = await c.get(f"/workflows/code/template?wf_type={wf_type}")
            assert r.status_code == 200
            assert "content" in r.json()


@pytest.mark.asyncio
async def test_workflow_code_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/nonexistent/code")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_workflow_code_invalid_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/../../etc/passwd/code")
        assert r.status_code in (400, 403, 404)


@pytest.mark.asyncio
async def test_save_workflow_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/workflows/test_wf/code", content=b"# test workflow")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "saved"
        assert "commit" in data


@pytest.mark.asyncio
async def test_delete_workflow_code_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/workflows/nonexistent/code")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_save_delete_workflow_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/workflows/temp_wf/code", content=b"# temp")
        r = await c.delete("/workflows/temp_wf/code")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_save_workflow_code_writes_audit_row():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/workflows/audited_wf/code", content=b"# test workflow")

    rows = await _audit_rows("workflow", "audited_wf")
    assert len(rows) == 1
    assert rows[0].action == "workflow.update"
    assert rows[0].actor_name == "test_admin"


@pytest.mark.asyncio
async def test_delete_workflow_code_writes_audit_row():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/workflows/to_delete_wf/code", content=b"# test workflow")
        await c.delete("/workflows/to_delete_wf/code")

    rows = await _audit_rows("workflow", "to_delete_wf")
    actions = {row.action for row in rows}
    assert actions == {"workflow.update", "workflow.delete"}


@pytest.mark.asyncio
async def test_enable_disable_workflow_writes_audit_row():
    from orchestrator.models import ConcurrencyPolicy
    from orchestrator.models.workflow_meta import WorkflowMeta

    app.state.job_manager.set_metas([WorkflowMeta(
        name="toggle_wf", type="scheduled", enabled=False,
        concurrency=ConcurrencyPolicy.FORBID,
    )])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/workflows/toggle_wf/enable")
        await c.post("/workflows/toggle_wf/disable")

    rows = await _audit_rows("workflow", "toggle_wf")
    actions = {row.action for row in rows}
    assert "workflow.enable" in actions
    assert "workflow.disable" in actions
