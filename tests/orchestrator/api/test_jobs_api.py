import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.main import app
from orchestrator.models.job import WorkflowJob


@pytest.mark.asyncio
async def test_list_jobs_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/jobs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_list_jobs_with_filters():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/jobs?status=pending&limit=10&offset=0")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_job_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/jobs/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_job_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs", json={"workflow_name": "NonExistent", "context": {}})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_cancel_job_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs/nonexistent/cancel")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_cancel_job_writes_audit_row():
    job = WorkflowJob(workflow_name="audited_wf")
    await app.state.job_store.save(job)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(f"/jobs/{job.id}/cancel")
        assert r.status_code == 200

    async with app.state.db_session_factory() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.resource_type == "job", AuditLog.resource_id == job.id)
        )
        rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].action == "job.cancel"


@pytest.mark.asyncio
async def test_create_job_wrong_body():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs", json={"wrong": "field"})
        assert r.status_code == 422
