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


@pytest.mark.asyncio
async def test_log_stream_file_not_yet_created_terminal_job_ends_cleanly():
    """M5: log_path is assigned at enqueue time, but the file is only created
    when the worker picks the job up — streaming a job whose file never
    appeared (e.g. it failed before the worker started it) must not raise
    FileNotFoundError inside the SSE generator."""
    from orchestrator.models.job import WorkflowJob
    from orchestrator.models import JobStatus

    job = WorkflowJob(
        id="test-log-stream-missing-file",
        workflow_name="test",
        status=JobStatus.FAILED,
        log_path="/nonexistent/path/does-not-exist.log",
    )
    app.state.job_store._jobs[job.id] = job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/logs/test-log-stream-missing-file/stream")
        assert r.status_code == 200
        assert r.text == ""
