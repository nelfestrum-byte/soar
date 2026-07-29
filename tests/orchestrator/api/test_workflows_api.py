import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.core.git_manager import GitManager
from orchestrator.main import app

VALID_WF_CODE = (
    "from soar.workflows.base import ManualWorkflow\n\n\n"
    "class TestWorkflow(ManualWorkflow):\n"
    "    def run(self, context):\n        return {}\n"
).encode()


async def _audit_rows(resource_type: str, resource_id: str) -> list[AuditLog]:
    async with app.state.db_session_factory() as session:
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id
            )
        )
        return list(result.scalars())


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


def _viewer() -> CurrentUser:
    return CurrentUser(id=9, role="viewer", type="user", username="test_viewer")


def _analyst() -> CurrentUser:
    return CurrentUser(id=2, role="analyst", type="user", username="test_analyst")


@pytest.mark.asyncio
async def test_get_workflow_hides_token_from_viewer():
    """M13: the webhook token is the only thing guarding that workflow's
    trigger endpoint — `viewer` (the lowest-privilege read-only role) must
    not receive it."""
    from orchestrator.models import ConcurrencyPolicy
    from orchestrator.models.workflow_meta import WorkflowMeta

    meta = WorkflowMeta(
        name="token_wf", type="webhook", enabled=True,
        path="/webhook/token_wf", token="super-secret-token",
        timeout=300, concurrency=ConcurrencyPolicy.ALLOW,
    )
    app.state.job_manager.set_metas([meta])

    app.dependency_overrides[get_current_user] = _viewer
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/workflows/token_wf")
            assert r.status_code == 200
            assert "token" not in r.json()

            r = await c.get("/workflows")
            assert r.status_code == 200
            item = next(w for w in r.json() if w["name"] == "token_wf")
            assert "token" not in item
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_get_workflow_keeps_token_for_analyst():
    from orchestrator.models import ConcurrencyPolicy
    from orchestrator.models.workflow_meta import WorkflowMeta

    meta = WorkflowMeta(
        name="token_wf_analyst", type="webhook", enabled=True,
        path="/webhook/token_wf_analyst", token="super-secret-token",
        timeout=300, concurrency=ConcurrencyPolicy.ALLOW,
    )
    app.state.job_manager.set_metas([meta])

    app.dependency_overrides[get_current_user] = _analyst
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/workflows/token_wf_analyst")
            assert r.status_code == 200
            assert r.json()["token"] == "super-secret-token"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


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


DOCUMENTED_WF_CODE = (
    "from soar.workflows.base import ManualWorkflow\n\n\n"
    "class DocumentedWorkflow(ManualWorkflow):\n"
    '    """Explains what this workflow does."""\n\n'
    "    def run(self, context):\n        return {}\n"
).encode()


@pytest.mark.asyncio
async def test_list_and_get_workflow_include_docstring():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/workflows/documented_wf/code", content=DOCUMENTED_WF_CODE)

        r = await c.get("/workflows/documented_wf")
        assert r.status_code == 200
        assert r.json()["docstring"] == "Explains what this workflow does."

        r = await c.get("/workflows")
        item = next(w for w in r.json() if w["name"] == "documented_wf")
        assert item["docstring"] == "Explains what this workflow does."


@pytest.mark.asyncio
async def test_save_workflow_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/workflows/test_wf/code", content=VALID_WF_CODE)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "saved"
        assert "commit" in data


@pytest.mark.asyncio
async def test_save_workflow_code_invalid_syntax():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/workflows/bad_wf/code", content=b"def broken(:\n    pass")
        assert r.status_code == 422
        r = await c.get("/workflows/bad_wf/code")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_save_workflow_code_missing_base_class():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/workflows/not_a_wf/code", content=b"class NotAWorkflow:\n    pass\n")
        assert r.status_code == 422
        r = await c.get("/workflows/not_a_wf/code")
        assert r.status_code == 404


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
        await c.put("/workflows/temp_wf/code", content=VALID_WF_CODE)
        r = await c.delete("/workflows/temp_wf/code")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_save_workflow_code_writes_audit_row():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/workflows/audited_wf/code", content=VALID_WF_CODE)

    rows = await _audit_rows("workflow", "audited_wf")
    assert len(rows) == 1
    assert rows[0].action == "workflow.update"
    assert rows[0].actor_name == "test_admin"


@pytest.mark.asyncio
async def test_delete_workflow_code_writes_audit_row():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/workflows/to_delete_wf/code", content=VALID_WF_CODE)
        await c.delete("/workflows/to_delete_wf/code")

    rows = await _audit_rows("workflow", "to_delete_wf")
    actions = {row.action for row in rows}
    assert actions == {"workflow.update", "workflow.delete"}


@pytest.mark.asyncio
async def test_workflow_history_diff_restore(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.put("/workflows/hist_wf/code", content=VALID_WF_CODE)
        first_commit = r1.json()["commit"]

        updated_code = VALID_WF_CODE + b"\n# v2\n"
        await c.put("/workflows/hist_wf/code", content=updated_code)

        r = await c.get("/workflows/hist_wf/code/history")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) >= 2

        r = await c.get(f"/workflows/hist_wf/code/history/{first_commit}")
        assert r.status_code == 200
        assert r.json()["content"] == VALID_WF_CODE.decode()

        r = await c.get(f"/workflows/hist_wf/code/diff?a={first_commit}&b={entries[0]['hash']}")
        assert r.status_code == 200
        assert "diff" in r.json()

        r = await c.post("/workflows/hist_wf/code/restore", json={"commit": first_commit})
        assert r.status_code == 200
        assert r.json()["status"] == "restored"

        r = await c.get("/workflows/hist_wf/code")
        assert r.json()["content"] == VALID_WF_CODE.decode()

    rows = await _audit_rows("workflow", "hist_wf")
    actions = {row.action for row in rows}
    assert "workflow.restore" in actions


@pytest.mark.asyncio
async def test_webhook_token_stable_across_resaves():
    from orchestrator.api.workflows import WEBHOOK_TEMPLATE

    code_v1 = WEBHOOK_TEMPLATE.format(name="TokenTestWf", path="token-test").encode()
    code_v2 = (WEBHOOK_TEMPLATE.format(name="TokenTestWf", path="token-test") + "\n# v2\n").encode()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/workflows/token_test_wf/code", content=code_v1)
        r1 = await c.get("/workflows/token_test_wf")
        token1 = r1.json()["token"]
        assert token1

        await c.put("/workflows/token_test_wf/code", content=code_v2)
        r2 = await c.get("/workflows/token_test_wf")
        token2 = r2.json()["token"]

    assert token1 == token2


@pytest.mark.asyncio
async def test_workflow_restore_requires_admin(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.put("/workflows/rbac_wf/code", content=VALID_WF_CODE)
        first_commit = r1.json()["commit"]

        def _viewer():
            return CurrentUser(id=2, role="viewer", type="user", username="test_viewer")

        app.dependency_overrides[get_current_user] = _viewer
        try:
            r = await c.get("/workflows/rbac_wf/code/history")
            assert r.status_code == 200
            r = await c.post("/workflows/rbac_wf/code/restore", json={"commit": first_commit})
            assert r.status_code == 403
        finally:
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=1, role="admin", type="user", username="test_admin"
            )


@pytest.mark.asyncio
async def test_enable_disable_workflow_writes_audit_row():
    from orchestrator.models import ConcurrencyPolicy
    from orchestrator.models.workflow_meta import WorkflowMeta

    app.state.job_manager.set_metas([WorkflowMeta(
        name="toggle_wf", type="scheduled", enabled=False,
        concurrency=ConcurrencyPolicy.FORBID,
    )])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/workflows/toggle_wf/enable")
        await c.post("/workflows/toggle_wf/disable")

    rows = await _audit_rows("workflow", "toggle_wf")
    actions = {row.action for row in rows}
    assert "workflow.enable" in actions
    assert "workflow.disable" in actions
