import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.auth.dependencies import CurrentUser, get_current_user
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
async def test_get_system_prompt_reads_configured_file(tmp_path):
    path = tmp_path / "system_prompt.md"
    path.write_text("# System prompt\nSOAR is a deterministic automation engine.\n", encoding="utf-8")
    app.state.config.soar.system_prompt_path = str(path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/prompts/system")
        assert r.status_code == 200
        assert "SOAR is a deterministic automation engine." in r.json()["content"]


@pytest.mark.asyncio
async def test_get_system_prompt_missing_file_404(tmp_path):
    app.state.config.soar.system_prompt_path = str(tmp_path / "does_not_exist.md")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/prompts/system")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_user_prompt_defaults_to_null(tmp_path):
    app.state.config.git.workflows_repo = str(tmp_path / "data")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/prompts/user")
        assert r.status_code == 200
        assert r.json()["content"] is None


@pytest.mark.asyncio
async def test_put_user_prompt_saves_commits_and_audits(tmp_path):
    app.state.config.git.workflows_repo = str(tmp_path / "data")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/prompts/user", json={"content": "Custom operator instructions."})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "saved"
        assert data["commit"]

        r = await c.get("/prompts/user")
        assert r.status_code == 200
        assert r.json()["content"] == "Custom operator instructions."

    rows = await _audit_rows("prompt", "user")
    actions = {row.action for row in rows}
    assert "prompt.update_user" in actions


@pytest.mark.asyncio
async def test_put_user_prompt_requires_admin(tmp_path):
    app.state.config.git.workflows_repo = str(tmp_path / "data")

    def _viewer():
        return CurrentUser(id=2, role="viewer", type="user", username="test_viewer")

    app.dependency_overrides[get_current_user] = _viewer
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.put("/prompts/user", json={"content": "nope"})
            assert r.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=1, role="admin", type="user", username="test_admin"
        )
