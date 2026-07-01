import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from orchestrator.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_archive():
    """Create a sample export archive for testing."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        manifest = {
            "version": "1.0",
            "created_at": "20260701-120000",
            "connectors": ["test_connector"],
            "actions": ["test_action"],
            "workflows": ["test_workflow"],
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("connectors/test_connector/code.py", "class TestConnector: pass")
        zf.writestr("connectors/test_connector/config.yml", "instances:\n  test: {}")
        zf.writestr("actions/test_action.py", "def test_action(): pass")
        zf.writestr("workflows/test_workflow.py", "class TestWorkflow: pass")
        zf.writestr("state.yaml", json.dumps({"workflows": {"test_workflow": "enabled"}}))
    buffer.seek(0)
    return buffer


def test_export_returns_zip(client):
    response = client.post("/transfer/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    content = io.BytesIO(response.content)
    with zipfile.ZipFile(content) as zf:
        assert "manifest.json" in zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
        assert "version" in manifest


def test_import_returns_conflicts(client, sample_archive):
    # Create connector first
    client.post("/connectors/test_connector")

    response = client.post(
        "/transfer/import",
        files={"file": ("export.zip", sample_archive, "application/zip")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "conflicts"
    assert len(data["conflicts"]) > 0


def test_import_with_force(client, sample_archive):
    response = client.post(
        "/transfer/import?force=true",
        files={"file": ("export.zip", sample_archive, "application/zip")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "imported"


def test_import_invalid_file(client):
    response = client.post(
        "/transfer/import",
        files={"file": ("test.txt", b"not a zip", "text/plain")},
    )
    assert response.status_code == 400
