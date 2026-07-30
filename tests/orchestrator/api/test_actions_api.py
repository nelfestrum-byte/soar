from unittest.mock import patch

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
async def test_list_actions_includes_summary():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put(
            "/actions/summarized_action",
            content=b'def summarized_action():\n    """Do the thing."""\n    pass\n',
        )
        r = await c.get("/actions")
        assert r.status_code == 200
        item = next(a for a in r.json() if a["name"] == "summarized_action")
        assert item["summary"] == "Do the thing."


@pytest.mark.asyncio
async def test_list_actions_shows_every_public_function_in_a_file():
    """E7: a file with multiple public top-level functions must list all of
    them, not just the one matching the filename (old ActionsRegistry
    behavior)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put(
            "/actions/multi_export_action",
            content=(
                b'def multi_export_action(ip):\n    """Primary entry."""\n    pass\n\n\n'
                b'def multi_export_action_extra(ip):\n    """Secondary entry."""\n    pass\n'
            ),
        )
        r = await c.get("/actions")
        assert r.status_code == 200
        names = {a["name"] for a in r.json()}
        assert "multi_export_action" in names
        assert "multi_export_action_extra" in names
        extra = next(a for a in r.json() if a["name"] == "multi_export_action_extra")
        assert extra["file"] == "multi_export_action"
        assert extra["summary"] == "Secondary entry."


@pytest.mark.asyncio
async def test_list_actions_does_not_import_content():
    """After Phase 1's runtime boundary, the orchestrator process must never
    import actions_dir content — GET /actions is AST-only. Patching
    ActionsRegistry's own import machinery (rather than the global
    importlib.import_module, which the ASGI stack also uses internally for
    unrelated things) targets exactly the "content import" this test cares
    about."""
    transport = ASGITransport(app=app)
    with (
        patch("soar.actions.ActionsRegistry._discover", side_effect=AssertionError("must not import")) as mock_discover,
        patch("soar.actions.ActionsRegistry._discover_external", side_effect=AssertionError("must not import")) as mock_discover_ext,
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/actions")
        assert r.status_code == 200
    mock_discover.assert_not_called()
    mock_discover_ext.assert_not_called()


@pytest.mark.asyncio
async def test_describe_action():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put(
            "/actions/described_action",
            content=b'def described_action(indicator):\n    """Describe me."""\n    pass\n',
        )
        r = await c.get("/actions/described_action/describe")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "described_action"
        assert data["signature"] == "(indicator)"
        assert data["docstring"] == "Describe me."
        assert data["module"] == "described_action"


@pytest.mark.asyncio
async def test_describe_action_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/nonexistent/describe")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_describe_action_function_name_mismatch_is_404():
    """File exists but its function isn't named after the file — describe
    must not 500, since ActionsRegistry looks up actions by file name.
    Written directly to disk: the PUT endpoint's validate_action_code
    already rejects a mismatched name at save time, so this state can only
    arise from a file placed on disk outside the API."""
    import os
    actions_dir = app.state.config.soar.actions_dir
    os.makedirs(actions_dir, exist_ok=True)
    with open(os.path.join(actions_dir, "mismatched_action.py"), "w") as f:
        f.write("def other_name():\n    pass\n")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/mismatched_action/describe")
        assert r.status_code == 404


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
