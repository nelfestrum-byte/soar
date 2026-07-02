import json
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


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
        r = await c.put("/connectors/save_conn/code", content=b"# connector code")
        assert r.status_code == 200
        assert r.json()["status"] == "saved"


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
