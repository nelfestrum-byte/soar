"""Stage 3 (P7): role `agent` gets code+jobs access but not user/audit/transfer.

Covers the [S4] table from docs/compose/specs/2026-07-22-agent-devloop-stage3-design.md —
one representative case per _RO/_RW/_ADMIN/_ANALYST constant that gained `agent`,
plus the explicit 403s on routes that intentionally did not.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.core.git_manager import GitManager
from orchestrator.main import app

VALID_WF_CODE = (
    "from soar.workflows.base import ManualWorkflow\n\n\n"
    "class TestWorkflow(ManualWorkflow):\n"
    "    def run(self, context):\n        return {}\n"
).encode()

VALID_CONNECTOR_CODE = (
    "from soar.connectors.base import BaseConnector\n\n\n"
    "class MyConnector(BaseConnector):\n"
    "    def _connect_impl(self):\n        self._connected = True\n\n"
    "    def disconnect(self):\n        self._connected = False\n"
).encode()


def _agent() -> CurrentUser:
    return CurrentUser(id=3, role="agent", type="user", username="test_agent")


def _admin() -> CurrentUser:
    return CurrentUser(id=1, role="admin", type="user", username="test_admin")


@pytest.fixture
def as_agent():
    app.dependency_overrides[get_current_user] = _agent
    yield
    app.dependency_overrides[get_current_user] = _admin


# ── _RO: list/get/describe across actions, connectors, workflows, jobs, tools, status, prompts ──

@pytest.mark.asyncio
async def test_agent_can_list_actions(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_agent_can_list_connectors(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_agent_can_list_workflows(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_agent_can_list_jobs(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/jobs")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_agent_can_list_tools(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/tools")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_agent_can_get_status(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/status")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_agent_can_read_prompts(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/prompts/system")
        assert r.status_code in (200, 404)  # 404 = no system prompt configured, not 403
        r2 = await c.get("/prompts/user")
        assert r2.status_code == 200


# ── _RW/_ADMIN/_ANALYST: agent can write code and manage jobs ──

@pytest.mark.asyncio
async def test_agent_can_write_and_delete_action_code(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/actions/agent_action", content=b"def agent_action():\n    pass\n")
        assert r.status_code == 200
        r2 = await c.delete("/actions/agent_action")
        assert r2.status_code == 200


@pytest.mark.asyncio
async def test_agent_can_create_and_delete_connector(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/connectors/agent_conn")
        assert r.status_code == 200
        r2 = await c.delete("/connectors/agent_conn")
        assert r2.status_code == 200


@pytest.mark.asyncio
async def test_agent_cannot_write_connector_code(as_agent):
    # B3: PUT /connectors/{name}/code is admin-only — HIDDEN_FIELDS is the
    # redaction policy itself, not code agent should be able to rewrite.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/connectors/agent_conn_code/code", content=VALID_CONNECTOR_CODE)
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_agent_can_preview_connector_spec(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors/preview")
        assert r.status_code != 403


@pytest.mark.asyncio
async def test_agent_can_write_and_delete_workflow_code(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/workflows/agent_wf/code", content=VALID_WF_CODE)
        assert r.status_code == 200
        r2 = await c.delete("/workflows/agent_wf/code")
        assert r2.status_code == 200


@pytest.mark.asyncio
async def test_agent_can_enable_workflow(as_agent):
    from orchestrator.models import ConcurrencyPolicy
    from orchestrator.models.workflow_meta import WorkflowMeta

    app.state.job_manager.set_metas([WorkflowMeta(
        name="agent_toggle_wf", type="scheduled", enabled=False,
        concurrency=ConcurrencyPolicy.FORBID,
    )])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/workflows/agent_toggle_wf/enable")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_agent_can_create_job(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs", json={"workflow_name": "nonexistent"})
        # 404 = workflow doesn't exist, but the RBAC check itself passed (not 403)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_agent_can_cancel_job(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs/nonexistent-id/cancel")
        assert r.status_code == 404  # RBAC passed, job just doesn't exist


@pytest.mark.asyncio
async def test_agent_can_get_job_log(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/logs/nonexistent-id")
        assert r.status_code == 404  # RBAC passed, job just doesn't exist


@pytest.mark.asyncio
async def test_agent_can_restore_action_code(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.put("/actions/agent_restore_action", content=b"def agent_restore_action():\n    pass\n")
        first_commit = r1.json()["commit"]

        app.dependency_overrides[get_current_user] = _agent
        try:
            r = await c.post("/actions/agent_restore_action/restore", json={"commit": first_commit})
            assert r.status_code == 200
        finally:
            app.dependency_overrides[get_current_user] = _admin


@pytest.mark.asyncio
async def test_agent_can_restore_workflow_code(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.put("/workflows/agent_restore_wf/code", content=VALID_WF_CODE)
        first_commit = r1.json()["commit"]
        await c.put("/workflows/agent_restore_wf/code", content=VALID_WF_CODE + b"\n# v2\n")

        app.dependency_overrides[get_current_user] = _agent
        try:
            r = await c.post("/workflows/agent_restore_wf/code/restore", json={"commit": first_commit})
            assert r.status_code == 200
        finally:
            app.dependency_overrides[get_current_user] = _admin


@pytest.mark.asyncio
async def test_agent_can_restore_connector_code(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.put("/connectors/agent_restore_conn/code", content=VALID_CONNECTOR_CODE)
        first_commit = r1.json()["commit"]

        app.dependency_overrides[get_current_user] = _agent
        try:
            r = await c.post("/connectors/agent_restore_conn/code/restore", json={"commit": first_commit})
            assert r.status_code == 200
        finally:
            app.dependency_overrides[get_current_user] = _admin


# ── explicit exclusions: admin-only literal routes, PUT /prompts/user ──

@pytest.mark.asyncio
async def test_agent_cannot_create_user(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/auth/users", json={"username": "x", "password": "password1", "role": "viewer"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_agent_cannot_create_api_key(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/auth/keys", json={"name": "x", "role": "service"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_agent_cannot_read_audit_log(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/audit-log")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_agent_cannot_access_transfer(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/transfer/export")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_agent_cannot_save_user_prompt(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/prompts/user", json={"content": "hi"})
        assert r.status_code == 403


# ── regression: existing roles unaffected ──

@pytest.mark.asyncio
async def test_viewer_still_cannot_write_action_code():
    def _viewer():
        return CurrentUser(id=2, role="viewer", type="user", username="test_viewer")

    app.dependency_overrides[get_current_user] = _viewer
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.put("/actions/viewer_action", content=b"def viewer_action():\n    pass\n")
            assert r.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = _admin


@pytest.mark.asyncio
async def test_analyst_still_cannot_write_workflow_code():
    def _analyst():
        return CurrentUser(id=4, role="analyst", type="user", username="test_analyst")

    app.dependency_overrides[get_current_user] = _analyst
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.put("/workflows/analyst_wf/code", content=VALID_WF_CODE)
            assert r.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = _admin


@pytest.mark.asyncio
async def test_service_can_still_create_job():
    def _service():
        return CurrentUser(id=5, role="service", type="user", username="test_service")

    app.dependency_overrides[get_current_user] = _service
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/jobs", json={"workflow_name": "nonexistent"})
            assert r.status_code == 404
    finally:
        app.dependency_overrides[get_current_user] = _admin
