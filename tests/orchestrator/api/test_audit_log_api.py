import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.main import app


def _mock_viewer() -> CurrentUser:
    return CurrentUser(id=2, role="viewer", type="user", username="test_viewer")


@pytest.mark.asyncio
async def test_audit_log_forbidden_for_non_admin(setup_app_state):
    app.dependency_overrides[get_current_user] = _mock_viewer
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/audit-log")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_audit_log_admin_sees_rows_from_prior_mutation(setup_app_state):
    # setup_app_state's autouse fixture mocks get_current_user as admin already
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/al_action", content=b"# test")
        r = await c.get("/audit-log")

    assert r.status_code == 200
    rows = r.json()
    assert any(row["resource_type"] == "action" and row["resource_id"] == "al_action" for row in rows)


@pytest.mark.asyncio
async def test_audit_log_filters_by_resource_type(setup_app_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/filter_action", content=b"# test")
        await c.put("/workflows/filter_wf/code", content=b"# test")

        r = await c.get("/audit-log?resource_type=action")
        assert r.status_code == 200
        rows = r.json()
        assert all(row["resource_type"] == "action" for row in rows)
        assert any(row["resource_id"] == "filter_action" for row in rows)
        assert not any(row["resource_id"] == "filter_wf" for row in rows)


@pytest.mark.asyncio
async def test_audit_log_filters_by_action(setup_app_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/act_filter", content=b"# test")
        await c.delete("/actions/act_filter")

        r = await c.get("/audit-log?action=action.delete")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 1
        assert all(row["action"] == "action.delete" for row in rows)


@pytest.mark.asyncio
async def test_audit_log_pagination_limit(setup_app_state):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for i in range(3):
            await c.put(f"/actions/page_action_{i}", content=b"# test")

        r = await c.get("/audit-log?limit=1")
        assert r.status_code == 200
        assert len(r.json()) == 1
