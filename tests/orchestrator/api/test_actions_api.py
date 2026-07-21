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
async def test_list_actions():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_action_template():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/template")
        assert r.status_code == 200
        assert "content" in r.json()


@pytest.mark.asyncio
async def test_action_template_custom():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/template?name=custom&description=Test")
        assert r.status_code == 200
        content = r.json()["content"]
        assert "custom" in content


@pytest.mark.asyncio
async def test_get_action_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_action_invalid_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/../../secret")
        assert r.status_code in (400, 403, 404)


@pytest.mark.asyncio
async def test_save_action():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/actions/test_action", content=b"# test action")
        assert r.status_code == 200
        assert r.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_get_saved_action():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/saved_action", content=b"# content")
        r = await c.get("/actions/saved_action")
        assert r.status_code == 200
        assert r.json()["content"] == "# content"


@pytest.mark.asyncio
async def test_delete_action_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/actions/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_action():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/to_delete", content=b"# del")
        r = await c.delete("/actions/to_delete")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_save_delete_action_writes_audit_rows():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/audited_action", content=b"# test action")
        await c.delete("/actions/audited_action")

    rows = await _audit_rows("action", "audited_action")
    actions = {row.action for row in rows}
    assert actions == {"action.update", "action.delete"}
