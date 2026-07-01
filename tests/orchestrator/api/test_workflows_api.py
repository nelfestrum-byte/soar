import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


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
