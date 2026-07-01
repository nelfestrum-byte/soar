import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_log_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/logs/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_log_stream_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/logs/nonexistent/stream")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_log_no_log_path():
    from orchestrator.models.job import WorkflowJob
    from orchestrator.models import JobStatus

    job = WorkflowJob(
        id="test-log-no-path",
        workflow_name="test",
        status=JobStatus.COMPLETED,
        log_path=None,
    )
    app.state.job_store._jobs[job.id] = job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/logs/test-log-no-path")
        assert r.status_code == 404
