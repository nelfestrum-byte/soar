"""POST /connectors/pack/install — conflict-preflight/force (mirrors
/transfer/import), admin-only, audit trail. Synthetic pack fixture only,
see tests/orchestrator/core/test_pack_install.py docstring."""

import io
import zipfile

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from orchestrator.audit.models import AuditLog
from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.main import app

_FAKE_CONN_SRC = (
    "from typing import ClassVar\n\n"
    "from soar.connectors.base import BaseConnector\n\n\n"
    "class FakeConnConnector(BaseConnector):\n"
    "    MUTATING_METHODS: ClassVar[set[str]] = set()\n\n"
    "    def _connect_impl(self):\n"
    "        self._connected = True\n\n"
    "    def disconnect(self):\n"
    "        self._connected = False\n"
)


def _manifest(version="1.0.0", name="test-pack", imports=None):
    return {
        "name": name,
        "version": version,
        "runtime_version": "1",
        "connectors": [
            {
                "name": "fake_conn",
                "path": "connectors/fake_conn/fake_conn.py",
                "imports": imports or [],
                "mutating_methods": [],
            },
        ],
    }


def _pack_zip_bytes(manifest: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.yaml", yaml.safe_dump(manifest))
        zf.writestr("connectors/fake_conn/fake_conn.py", _FAKE_CONN_SRC)
        zf.writestr("connectors/fake_conn/__init__.py", "")
    return buffer.getvalue()


@pytest.fixture
def client():
    return TestClient(app)


def _upload(client, manifest, **kw):
    return client.post(
        "/connectors/pack/install",
        files={"file": ("pack.zip", _pack_zip_bytes(manifest), "application/zip")},
        **kw,
    )


async def _audit_rows(action: str) -> list[AuditLog]:
    async with app.state.db_session_factory() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.action == action))
        return list(result.scalars())


def test_install_clean_pack_installs_immediately(client):
    response = _upload(client, _manifest())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "installed"
    assert data["installed"]["new"] == ["fake_conn"]


def test_install_second_time_same_version_is_noop(client):
    _upload(client, _manifest())
    response = _upload(client, _manifest())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "installed"
    assert data["installed"] == {"new": [], "update": []}


def test_install_new_version_without_force_returns_conflicts(client):
    _upload(client, _manifest(version="1.0.0"))
    response = _upload(client, _manifest(version="2.0.0"))
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "conflicts"
    assert data["conflicts"] == ["fake_conn"]


def test_install_new_version_with_force_installs(client):
    _upload(client, _manifest(version="1.0.0"))
    response = _upload(client, _manifest(version="2.0.0"), params={"force": "true"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "installed"
    assert data["installed"]["update"] == ["fake_conn"]


def test_install_missing_dependency_rejected_before_write(client):
    response = _upload(client, _manifest(imports=["definitely_not_a_real_sdk"]))
    assert response.status_code == 400
    assert "definitely_not_a_real_sdk" in response.json()["detail"]


def test_install_incompatible_runtime_version_rejected(client):
    manifest = _manifest()
    manifest["runtime_version"] = "999"
    response = _upload(client, manifest)
    assert response.status_code == 400


def test_install_invalid_zip_rejected(client):
    response = client.post(
        "/connectors/pack/install",
        files={"file": ("pack.zip", b"not a zip", "application/zip")},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("role", ["analyst", "viewer"])
def test_install_non_admin_forbidden(client, role):
    def _user() -> CurrentUser:
        return CurrentUser(id=2, role=role, type="user", username=f"test_{role}")

    app.dependency_overrides[get_current_user] = _user
    try:
        response = _upload(client, _manifest())
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_install_writes_audit_log(client):
    response = _upload(client, _manifest())
    assert response.status_code == 200

    rows = await _audit_rows("pack.install")
    assert len(rows) == 1
    assert rows[0].resource_type == "connector_pack"
    assert rows[0].actor_name == "test_admin"


@pytest.mark.asyncio
async def test_install_conflicts_write_no_audit_log(client):
    _upload(client, _manifest(version="1.0.0"))
    rows_after_clean_install = await _audit_rows("pack.install")
    assert len(rows_after_clean_install) == 1  # the clean 1.0.0 install itself

    response = _upload(client, _manifest(version="2.0.0"))
    assert response.json()["status"] == "conflicts"

    rows_after_conflict = await _audit_rows("pack.install")
    assert len(rows_after_conflict) == 1  # unchanged — the conflicting attempt wrote nothing
