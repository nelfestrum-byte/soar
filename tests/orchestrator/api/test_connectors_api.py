import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.core.git_manager import GitManager
from orchestrator.main import app

VALID_CONNECTOR_CODE = (
    "from soar.connectors.base import BaseConnector\n\n\n"
    "class MyConnector(BaseConnector):\n"
    "    def _connect_impl(self):\n        self._connected = True\n\n"
    "    def disconnect(self):\n        self._connected = False\n"
).encode()


async def _audit_rows(resource_type: str, resource_id: str) -> list[AuditLog]:
    async with app.state.db_session_factory() as session:
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id
            )
        )
        return list(result.scalars())


SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test Generated API", "version": "1.0.0"},
    "servers": [{"url": "https://api.test.com"}],
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}


@pytest.mark.asyncio
async def test_list_connectors():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_connector_template():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors/template")
        assert r.status_code == 200
        data = r.json()
        assert "code" in data
        assert "config" in data


@pytest.mark.asyncio
async def test_connector_template_custom():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors/template?name=my_conn&class_name=MyCustom")
        assert r.status_code == 200
        assert "MyCustomConnector" in r.json()["code"]


@pytest.mark.asyncio
async def test_create_connector():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/connectors/test_conn")
        assert r.status_code == 200
        assert r.json()["status"] == "created"


@pytest.mark.asyncio
async def test_create_connector_duplicate():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/dup_conn")
        r = await c.post("/connectors/dup_conn")
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_get_connector_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/code_conn")
        r = await c.get("/connectors/code_conn/code")
        assert r.status_code == 200
        assert "content" in r.json()


@pytest.mark.asyncio
async def test_get_connector_code_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors/nonexistent/code")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_save_connector_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/save_conn")
        r = await c.put("/connectors/save_conn/code", content=VALID_CONNECTOR_CODE)
        assert r.status_code == 200
        assert r.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_save_connector_code_invalid():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/bad_code_conn")
        r = await c.put("/connectors/bad_code_conn/code", content=b"class NotAConnector:\n    pass\n")
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_connector_config():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/conf_conn")
        r = await c.get("/connectors/conf_conn/config")
        assert r.status_code == 200
        assert "content" in r.json()


@pytest.mark.asyncio
async def test_save_connector_config():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/yml_conn")
        r = await c.put("/connectors/yml_conn/config", content=b"instances: {}")
        assert r.status_code == 200
        assert r.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_delete_connector_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/connectors/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_connector():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/del_conn")
        r = await c.delete("/connectors/del_conn")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_connectors_list_after_create_delete():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/list_test")
        r = await c.get("/connectors")
        names = [x["name"] for x in r.json()]
        assert "list_test" in names
        await c.delete("/connectors/list_test")
        r = await c.get("/connectors")
        names = [x["name"] for x in r.json()]
        assert "list_test" not in names


@pytest.mark.asyncio
async def test_generate_connector():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/generate",
            json={"spec": json.dumps(SAMPLE_SPEC), "name": "gen_test"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "gen_test"
        assert len(data["files"]) == 3


@pytest.mark.asyncio
async def test_connector_lifecycle_writes_audit_rows():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/audited_conn")
        await c.put("/connectors/audited_conn/code", content=VALID_CONNECTOR_CODE)
        await c.put("/connectors/audited_conn/config", content=b"instances: {}")
        await c.delete("/connectors/audited_conn")

    rows = await _audit_rows("connector", "audited_conn")
    actions = {row.action for row in rows}
    assert actions == {
        "connector.create", "connector.update_code", "connector.update_config", "connector.delete",
    }


@pytest.mark.asyncio
async def test_generate_connector_writes_audit_row():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post(
            "/connectors/generate",
            json={"spec": json.dumps(SAMPLE_SPEC), "name": "audited_gen"},
        )

    rows = await _audit_rows("connector", "audited_gen")
    assert len(rows) == 1
    assert rows[0].action == "connector.generate"


@pytest.mark.asyncio
async def test_generate_connector_invalid_spec():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/generate",
            json={"spec": "not valid yaml or json {{{", "name": "bad"},
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_generate_connector_invalid_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/generate",
            json={"spec": json.dumps(SAMPLE_SPEC), "name": "Invalid Name!"},
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_generated_connector_config():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Generate a connector
        r = await c.post(
            "/connectors/generate",
            json={"spec": json.dumps(SAMPLE_SPEC), "name": "gen_config_test"},
        )
        assert r.status_code == 200

        # Get config - should return the example.yml content
        r = await c.get("/connectors/gen_config_test/config")
        assert r.status_code == 200
        content = r.json()["content"]
        assert "instances:" in content
        assert "GenConfigTestConnector1:" in content
        assert "base_url:" in content


SAMPLE_SPEC_JSON = json.dumps({
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "servers": [{"url": "https://api.test.com"}],
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
})


@pytest.mark.asyncio
async def test_preview_connector():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/preview",
            json={"spec": SAMPLE_SPEC_JSON},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "Test API"
        assert len(data["endpoints"]) == 1
        assert data["endpoints"][0]["method"] == "GET"


@pytest.mark.asyncio
async def test_preview_invalid_spec():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/preview",
            json={"spec": "not valid"},
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_connector_code_history_diff_restore(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    v1 = VALID_CONNECTOR_CODE
    v2 = VALID_CONNECTOR_CODE + b"\n# v2\n"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/hist_conn")
        r1 = await c.put("/connectors/hist_conn/code", content=v1)
        first_commit = r1.json()["commit"]
        await c.put("/connectors/hist_conn/code", content=v2)

        r = await c.get("/connectors/hist_conn/code/history")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) >= 2

        r = await c.get(f"/connectors/hist_conn/code/history/{first_commit}")
        assert r.status_code == 200
        assert r.json()["content"] == v1.decode()

        r = await c.get(f"/connectors/hist_conn/code/diff?a={first_commit}&b={entries[0]['hash']}")
        assert r.status_code == 200
        assert "diff" in r.json()

        r = await c.post("/connectors/hist_conn/code/restore", json={"commit": first_commit})
        assert r.status_code == 200

        r = await c.get("/connectors/hist_conn/code")
        assert r.json()["content"] == v1.decode()

    rows = await _audit_rows("connector", "hist_conn")
    actions = {row.action for row in rows}
    assert "connector.restore_code" in actions


@pytest.mark.asyncio
async def test_connector_config_history_diff_restore(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    v1 = b"instances:\n  a: {}\n"
    v2 = b"instances:\n  a: {}\n  b: {}\n"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/hist_conf_conn")
        r1 = await c.put("/connectors/hist_conf_conn/config", content=v1)
        first_commit = r1.json()["commit"]
        await c.put("/connectors/hist_conf_conn/config", content=v2)

        r = await c.get("/connectors/hist_conf_conn/config/history")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) >= 2

        r = await c.get(f"/connectors/hist_conf_conn/config/history/{first_commit}")
        assert r.status_code == 200
        assert r.json()["content"] == v1.decode()

        r = await c.get(
            f"/connectors/hist_conf_conn/config/diff?a={first_commit}&b={entries[0]['hash']}"
        )
        assert r.status_code == 200
        assert "diff" in r.json()

        r = await c.post("/connectors/hist_conf_conn/config/restore", json={"commit": first_commit})
        assert r.status_code == 200

        r = await c.get("/connectors/hist_conf_conn/config")
        assert r.json()["content"] == v1.decode()

    rows = await _audit_rows("connector", "hist_conf_conn")
    actions = {row.action for row in rows}
    assert "connector.restore_config" in actions


@pytest.mark.asyncio
async def test_connector_restore_requires_admin(tmp_path):
    (tmp_path / ".gitkeep").write_text("")
    real_git = GitManager(repo_path=str(tmp_path), author_name="Test", author_email="test@test.com")
    await real_git.ensure_repo()
    app.state.git = real_git

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/rbac_conn")
        r1 = await c.put("/connectors/rbac_conn/code", content=VALID_CONNECTOR_CODE)
        first_commit = r1.json()["commit"]

        def _viewer():
            return CurrentUser(id=2, role="viewer", type="user", username="test_viewer")

        app.dependency_overrides[get_current_user] = _viewer
        try:
            r = await c.get("/connectors/rbac_conn/code/history")
            assert r.status_code == 200
            r = await c.post("/connectors/rbac_conn/code/restore", json={"commit": first_commit})
            assert r.status_code == 403
        finally:
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=1, role="admin", type="user", username="test_admin"
            )
