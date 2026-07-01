import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


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
async def test_create_job_wrong_body():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs", json={"wrong": "field"})
        assert r.status_code == 422
