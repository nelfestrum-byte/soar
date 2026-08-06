"""HIDDEN_FIELDS is the redaction policy, not ordinary connector code.

Role `agent` writes connector code (that is its job — it authors `__init__` and
knows which param is a credential), but may not *narrow* HIDDEN_FIELDS through
any of the three write paths, and redaction fails closed when the policy can't
be read at all. See docs/compose/specs/2026-08-06-connector-code-agent-unlock-design.md
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.core.git_manager import GitManager
from orchestrator.main import app

SECRET_CODE = (
    b"from typing import ClassVar\n\n"
    b"from soar.connectors.base import BaseConnector\n\n\n"
    b"class SecretConnector(BaseConnector):\n"
    b'    HIDDEN_FIELDS: ClassVar[set[str]] = {"api_key"}\n\n'
    b'    def __init__(self, instance_name: str, host: str = "h", api_key: str = ""):\n'
    b"        super().__init__(instance_name)\n"
    b"        self.host = host\n"
    b"        self.api_key = api_key\n\n"
    b"    def _connect_impl(self):\n        self._connected = True\n\n"
    b"    def disconnect(self):\n        self._connected = False\n"
)

WIDER_CODE = SECRET_CODE.replace(
    b'HIDDEN_FIELDS: ClassVar[set[str]] = {"api_key"}',
    b'HIDDEN_FIELDS: ClassVar[set[str]] = {"api_key", "host"}',
)

NARROWED_CODE = SECRET_CODE.replace(
    b'    HIDDEN_FIELDS: ClassVar[set[str]] = {"api_key"}\n\n', b""
)


def _agent():
    return CurrentUser(id=3, role="agent", type="user", username="test_agent")


def _admin():
    return CurrentUser(id=1, role="admin", type="user", username="test_admin")


@pytest.fixture
def as_agent():
    app.dependency_overrides[get_current_user] = _agent
    yield
    app.dependency_overrides[get_current_user] = _admin


def _code_on_disk(name: str) -> str:
    path = os.path.join(app.state.config.soar.connectors_dir, name, f"{name}.py")
    with open(path) as f:
        return f.read()


@pytest.mark.asyncio
async def test_agent_cannot_narrow_hidden_fields_via_put():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/narrow_conn")
        await c.put("/connectors/narrow_conn/code", content=SECRET_CODE)

        app.dependency_overrides[get_current_user] = _agent
        try:
            r = await c.put("/connectors/narrow_conn/code", content=NARROWED_CODE)
            assert r.status_code == 403
        finally:
            app.dependency_overrides[get_current_user] = _admin

    assert "api_key" in _code_on_disk("narrow_conn")
    assert "HIDDEN_FIELDS" in _code_on_disk("narrow_conn")


@pytest.mark.asyncio
async def test_agent_can_widen_hidden_fields(as_agent):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/widen_conn")
        r1 = await c.put("/connectors/widen_conn/code", content=SECRET_CODE)
        assert r1.status_code == 200
        r2 = await c.put("/connectors/widen_conn/code", content=WIDER_CODE)
        assert r2.status_code == 200

    assert '"host"' in _code_on_disk("widen_conn")


@pytest.mark.asyncio
async def test_admin_can_narrow_hidden_fields():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/admin_narrow_conn")
        await c.put("/connectors/admin_narrow_conn/code", content=SECRET_CODE)
        r = await c.put("/connectors/admin_narrow_conn/code", content=NARROWED_CODE)
        assert r.status_code == 200

    assert "HIDDEN_FIELDS" not in _code_on_disk("admin_narrow_conn")


@pytest.mark.asyncio
async def test_agent_cannot_narrow_hidden_fields_via_restore(tmp_path):
    """The B3 bypass: POST /connectors commits a template with an empty
    HIDDEN_FIELDS, so agent could restore *its own* commit to strip redaction
    without ever calling PUT /code."""
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(
        repo_path=str(tmp_path), author_name="Test", author_email="test@test.com"
    )
    await real_git.ensure_repo()
    app.state.git = real_git

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        app.dependency_overrides[get_current_user] = _agent
        try:
            r0 = await c.post("/connectors/restore_bypass_conn")
            template_commit = r0.json()["commit"]
        finally:
            app.dependency_overrides[get_current_user] = _admin

        assert template_commit
        await c.put("/connectors/restore_bypass_conn/code", content=SECRET_CODE)
        await c.put(
            "/connectors/restore_bypass_conn/config",
            content=b"instances:\n  a:\n    api_key: supersecret\n",
        )

        app.dependency_overrides[get_current_user] = _agent
        try:
            r = await c.post(
                "/connectors/restore_bypass_conn/code/restore",
                json={"commit": template_commit},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides[get_current_user] = _admin

        r2 = await c.get("/connectors/restore_bypass_conn/config")
        assert r2.status_code == 200
        assert "supersecret" not in r2.json()["content"]
        assert "********" in r2.json()["content"]


@pytest.mark.asyncio
async def test_admin_can_restore_narrowing_commit(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(
        repo_path=str(tmp_path), author_name="Test", author_email="test@test.com"
    )
    await real_git.ensure_repo()
    app.state.git = real_git

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r0 = await c.post("/connectors/admin_restore_conn")
        template_commit = r0.json()["commit"]
        await c.put("/connectors/admin_restore_conn/code", content=SECRET_CODE)

        r = await c.post(
            "/connectors/admin_restore_conn/code/restore",
            json={"commit": template_commit},
        )
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_unparseable_connector_code_redacts_everything():
    """Fail closed: an unreadable HIDDEN_FIELDS declaration must not mean
    'nothing is secret' — it means 'assume everything is'."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/broken_conn")
        await c.put("/connectors/broken_conn/code", content=SECRET_CODE)
        await c.put(
            "/connectors/broken_conn/config",
            content=b"instances:\n  a:\n    host: real-host\n    api_key: supersecret\n",
        )

        path = os.path.join(
            app.state.config.soar.connectors_dir, "broken_conn", "broken_conn.py"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write("class Broken(BaseConnector:\n    pass\n")

        r = await c.get("/connectors/broken_conn/config")
        assert r.status_code == 200
        content = r.json()["content"]
        assert "supersecret" not in content
        assert "real-host" not in content
        assert "********" in content


@pytest.mark.asyncio
async def test_missing_connector_code_redacts_everything():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/codeless_conn")
        await c.put("/connectors/codeless_conn/code", content=SECRET_CODE)
        await c.put(
            "/connectors/codeless_conn/config",
            content=b"instances:\n  a:\n    api_key: supersecret\n",
        )

        os.remove(
            os.path.join(
                app.state.config.soar.connectors_dir, "codeless_conn", "codeless_conn.py"
            )
        )

        r = await c.get("/connectors/codeless_conn/config")
        assert r.status_code == 200
        assert "supersecret" not in r.json()["content"]
