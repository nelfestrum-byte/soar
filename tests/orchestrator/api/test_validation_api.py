import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_empty_workflow_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows//code")
        assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_long_workflow_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/workflows/{'a' * 200}/code")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_invalid_chars_workflow_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/../../etc/passwd/code")
        assert r.status_code in (400, 403, 404)


@pytest.mark.asyncio
async def test_valid_name_passes():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/my_valid_workflow-1/code")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_empty_action_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions//")
        assert r.status_code in (307, 400, 404)


@pytest.mark.asyncio
async def test_long_action_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/actions/{'b' * 200}")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_invalid_chars_action_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/../../../secret")
        assert r.status_code in (400, 403, 404)
