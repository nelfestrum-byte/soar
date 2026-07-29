import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.main import app
from orchestrator.models import ConcurrencyPolicy
from orchestrator.models.job import WorkflowJob
from orchestrator.models.workflow_meta import WorkflowMeta


def _viewer() -> CurrentUser:
    return CurrentUser(id=9, role="viewer", type="user", username="test_viewer")


def _analyst() -> CurrentUser:
    return CurrentUser(id=2, role="analyst", type="user", username="test_analyst")


@pytest.fixture
def as_viewer():
    app.dependency_overrides[get_current_user] = _viewer
    yield
    app.dependency_overrides.pop(get_current_user, None)


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


@pytest.mark.asyncio
async def test_create_job_writes_audit_log():
    meta = WorkflowMeta(
        name="audited_create_wf", type="manual", enabled=True,
        path="audited_create_wf", timeout=300, concurrency=ConcurrencyPolicy.ALLOW,
    )
    app.state.job_manager.set_metas([meta])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs", json={"workflow_name": "audited_create_wf", "context": {}})
        assert r.status_code == 202
        job_id = r.json()["id"]

    async with app.state.db_session_factory() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.resource_type == "job", AuditLog.resource_id == job_id)
        )
        rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].action == "job.create"
    assert rows[0].detail["workflow_name"] == "audited_create_wf"


@pytest.mark.asyncio
async def test_create_job_not_found_writes_no_audit_log():
    async with app.state.db_session_factory() as session:
        before = len(list((await session.execute(select(AuditLog))).scalars()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs", json={"workflow_name": "NonExistent", "context": {}})
        assert r.status_code == 404

    async with app.state.db_session_factory() as session:
        after = len(list((await session.execute(select(AuditLog))).scalars()))
    assert after == before


@pytest.mark.asyncio
async def test_get_job_strips_context_for_viewer(as_viewer):
    """M12: job.context is the raw webhook payload / user-supplied context —
    it may carry secrets and isn't redacted. The lowest-privilege read-only
    role must not see it; analyst+ still do."""
    job = WorkflowJob(workflow_name="ctx_wf", context={"secret": "shhh"})
    await app.state.job_store.save(job)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/jobs/{job.id}")
        assert r.status_code == 200
        assert "context" not in r.json()


@pytest.mark.asyncio
async def test_list_jobs_strips_context_for_viewer(as_viewer):
    job = WorkflowJob(workflow_name="ctx_wf_list", context={"secret": "shhh"})
    await app.state.job_store.save(job)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/jobs", params={"workflow_name": "ctx_wf_list"})
        assert r.status_code == 200
        assert all("context" not in j for j in r.json())


@pytest.mark.asyncio
async def test_get_job_keeps_context_for_analyst():
    app.dependency_overrides[get_current_user] = _analyst
    try:
        job = WorkflowJob(workflow_name="ctx_wf_analyst", context={"secret": "shhh"})
        await app.state.job_store.save(job)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get(f"/jobs/{job.id}")
            assert r.status_code == 200
            assert r.json()["context"] == {"secret": "shhh"}
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_create_job_disabled_writes_no_audit_log():
    meta = WorkflowMeta(
        name="disabled_create_wf", type="manual", enabled=False,
        path="disabled_create_wf", timeout=300, concurrency=ConcurrencyPolicy.ALLOW,
    )
    app.state.job_manager.set_metas([meta])

    async with app.state.db_session_factory() as session:
        before = len(list((await session.execute(select(AuditLog))).scalars()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs", json={"workflow_name": "disabled_create_wf", "context": {}})
        assert r.status_code == 409

    async with app.state.db_session_factory() as session:
        after = len(list((await session.execute(select(AuditLog))).scalars()))
    assert after == before
