import io
import json
import os
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.main import app


@pytest.fixture
def client():
    return TestClient(app)


async def _audit_rows(action: str) -> list[AuditLog]:
    async with app.state.db_session_factory() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.action == action))
        return list(result.scalars())


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
        zf.writestr(
            "connectors/test_connector/code.py",
            "from soar.connectors.base import BaseConnector\n\n\nclass TestConnector(BaseConnector): pass\n",
        )
        zf.writestr("connectors/test_connector/config.yml", "instances:\n  test: {}")
        zf.writestr("actions/test_action.py", "def test_action(): pass")
        zf.writestr(
            "workflows/test_workflow.py",
            "from soar.workflows.base import BaseWorkflow\n\n\nclass TestWorkflow(BaseWorkflow): pass\n",
        )
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


def test_export_redacts_hidden_fields(client):
    client.post("/connectors/export_secret_conn")
    client.put(
        "/connectors/export_secret_conn/code",
        content=(
            "from typing import ClassVar\n\n"
            "from soar.connectors.base import BaseConnector\n\n\n"
            "class ExportSecretConnector(BaseConnector):\n"
            '    HIDDEN_FIELDS: ClassVar[set[str]] = {"password"}\n\n'
            "    def __init__(self, instance_name: str, password: str = \"\"):\n"
            "        super().__init__(instance_name)\n"
            "        self.password = password\n\n"
            "    def _connect_impl(self):\n        self._connected = True\n\n"
            "    def disconnect(self):\n        self._connected = False\n"
        ),
    )
    client.put(
        "/connectors/export_secret_conn/config",
        content=b"instances:\n  a:\n    password: supersecret\n",
    )

    response = client.post("/transfer/export")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        config_yml = zf.read("connectors/export_secret_conn/config.yml").decode()
    assert "supersecret" not in config_yml
    assert "********" in config_yml


@pytest.mark.asyncio
async def test_export_writes_audit_log(client):
    response = client.post("/transfer/export")
    assert response.status_code == 200

    rows = await _audit_rows("transfer.export")
    assert len(rows) == 1
    assert rows[0].resource_type == "transfer"
    assert rows[0].actor_name == "test_admin"


@pytest.mark.asyncio
async def test_import_writes_audit_log(client, sample_archive):
    response = client.post(
        "/transfer/import?force=true",
        files={"file": ("export.zip", sample_archive, "application/zip")},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "imported"

    rows = await _audit_rows("transfer.import")
    assert len(rows) == 1
    assert rows[0].resource_type == "transfer"


@pytest.mark.asyncio
async def test_import_conflicts_no_audit_log(client, sample_archive):
    client.post("/connectors/test_connector")

    response = client.post(
        "/transfer/import",
        files={"file": ("export.zip", sample_archive, "application/zip")},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "conflicts"

    rows = await _audit_rows("transfer.import")
    assert rows == []


def test_import_rejects_invalid_connector_code(client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        manifest = {
            "version": "1.0",
            "created_at": "20260701-120000",
            "connectors": ["bad_connector"],
            "actions": [],
            "workflows": [],
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("connectors/bad_connector/code.py", "class NotAConnector: pass\n")
    buffer.seek(0)

    response = client.post(
        "/transfer/import?force=true",
        files={"file": ("bad.zip", buffer, "application/zip")},
    )
    assert response.status_code == 422
    assert not os.path.exists(os.path.join(app.state.config.soar.connectors_dir, "bad_connector"))


def test_import_rejects_invalid_workflow_code(client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        manifest = {
            "version": "1.0",
            "created_at": "20260701-120000",
            "connectors": [],
            "actions": [],
            "workflows": ["bad_workflow"],
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("workflows/bad_workflow.py", "class NotAWorkflow: pass\n")
    buffer.seek(0)

    response = client.post(
        "/transfer/import?force=true",
        files={"file": ("bad.zip", buffer, "application/zip")},
    )
    assert response.status_code == 422
    assert not os.path.exists(os.path.join(app.state.config.soar.workflows_dir, "bad_workflow.py"))
