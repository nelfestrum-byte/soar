import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.core.git_manager import GitManager
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
        r = await c.put("/actions/test_action", content=b"def test_action():\n    pass\n")
        assert r.status_code == 200
        assert r.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_save_action_invalid_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/actions/bad_action", content=b"def other_name():\n    pass\n")
        assert r.status_code == 422
        r = await c.get("/actions/bad_action")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_saved_action():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/saved_action", content=b"def saved_action():\n    pass\n")
        r = await c.get("/actions/saved_action")
        assert r.status_code == 200
        assert r.json()["content"] == "def saved_action():\n    pass\n"


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
        await c.put("/actions/to_delete", content=b"def to_delete():\n    pass\n")
        r = await c.delete("/actions/to_delete")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_save_delete_action_writes_audit_rows():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/audited_action", content=b"def audited_action():\n    pass\n")
        await c.delete("/actions/audited_action")

    rows = await _audit_rows("action", "audited_action")
    actions = {row.action for row in rows}
    assert actions == {"action.update", "action.delete"}


@pytest.mark.asyncio
async def test_action_history_diff_restore(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    v1 = b"def hist_action():\n    return 1\n"
    v2 = b"def hist_action():\n    return 2\n"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.put("/actions/hist_action", content=v1)
        first_commit = r1.json()["commit"]
        await c.put("/actions/hist_action", content=v2)

        r = await c.get("/actions/hist_action/history")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) >= 2

        r = await c.get(f"/actions/hist_action/history/{first_commit}")
        assert r.status_code == 200
        assert r.json()["content"] == v1.decode()

        r = await c.get(f"/actions/hist_action/diff?a={first_commit}&b={entries[0]['hash']}")
        assert r.status_code == 200
        assert "diff" in r.json()

        r = await c.post("/actions/hist_action/restore", json={"commit": first_commit})
        assert r.status_code == 200

        r = await c.get("/actions/hist_action")
        assert r.json()["content"] == v1.decode()

    rows = await _audit_rows("action", "hist_action")
    actions = {row.action for row in rows}
    assert "action.restore" in actions


@pytest.mark.asyncio
async def test_action_restore_requires_admin(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.put("/actions/rbac_action", content=b"def rbac_action():\n    pass\n")
        first_commit = r1.json()["commit"]

        def _viewer():
            return CurrentUser(id=2, role="viewer", type="user", username="test_viewer")

        app.dependency_overrides[get_current_user] = _viewer
        try:
            r = await c.get("/actions/rbac_action/history")
            assert r.status_code == 200
            r = await c.post("/actions/rbac_action/restore", json={"commit": first_commit})
            assert r.status_code == 403
        finally:
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=1, role="admin", type="user", username="test_admin"
            )
