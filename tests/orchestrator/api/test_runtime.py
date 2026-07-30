import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.main import app


def _fake_dist(name: str, version: str, top_level: str | None = None):
    return SimpleNamespace(
        metadata={"Name": name},
        version=version,
        read_text=lambda fname: (top_level if fname == "top_level.txt" else None),
    )


@pytest.fixture(autouse=True)
def _set_content_python():
    app.state.content_python = sys.executable
    yield


@pytest.fixture
def as_viewer():
    def _viewer():
        return CurrentUser(id=2, role="viewer", type="user", username="test_viewer")
    app.dependency_overrides[get_current_user] = _viewer
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_get_runtime_returns_200_with_expected_shape(as_viewer):
    with patch("orchestrator.api.runtime._site_packages", return_value=["/fake/site-packages"]), \
         patch("importlib.metadata.distributions", return_value=[]):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/runtime")
            assert r.status_code == 200
            data = r.json()
            assert set(data.keys()) == {
                "runtime_version", "python_version", "guaranteed", "present_not_guaranteed",
            }
            assert isinstance(data["guaranteed"], list)
            assert isinstance(data["present_not_guaranteed"], list)


@pytest.mark.asyncio
async def test_get_runtime_guaranteed_only_from_contract_and_installed(as_viewer):
    dists = [
        _fake_dist("paramiko", "3.4.0"),
        _fake_dist("some-unrelated-pkg", "1.0.0", top_level="some_unrelated_pkg"),
    ]
    with patch("orchestrator.api.runtime._site_packages", return_value=["/fake/site-packages"]), \
         patch("importlib.metadata.distributions", return_value=dists):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/runtime")
            data = r.json()

            guaranteed_names = {g["distribution"] for g in data["guaranteed"]}
            assert guaranteed_names == {"paramiko"}

            entry = next(g for g in data["guaranteed"] if g["distribution"] == "paramiko")
            assert entry["version"] == "3.4.0"
            assert entry["import_names"] == ["paramiko"]
            assert entry["kind"] == "protocol"


@pytest.mark.asyncio
async def test_get_runtime_present_not_guaranteed_uses_top_level_txt(as_viewer):
    dists = [_fake_dist("some-unrelated-pkg", "1.0.0", top_level="some_unrelated_pkg")]
    with patch("orchestrator.api.runtime._site_packages", return_value=["/fake/site-packages"]), \
         patch("importlib.metadata.distributions", return_value=dists):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/runtime")
            data = r.json()

            assert len(data["present_not_guaranteed"]) == 1
            entry = data["present_not_guaranteed"][0]
            assert entry["distribution"] == "some-unrelated-pkg"
            assert entry["version"] == "1.0.0"
            assert entry["import_names"] == ["some_unrelated_pkg"]


@pytest.mark.asyncio
async def test_get_runtime_requires_auth_when_enabled():
    """Anonymous access is denied like the other read-only routes once auth
    is enabled (secret_key configured) — mirrors the RBAC pattern used
    elsewhere (see test_agent_role_rbac.py)."""
    def _unauthenticated_401():
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_current_user] = _unauthenticated_401
    try:
        with patch("orchestrator.api.runtime._site_packages", return_value=[]), \
             patch("importlib.metadata.distributions", return_value=[]):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                r = await c.get("/runtime")
                assert r.status_code == 401
    finally:
        app.dependency_overrides.pop(get_current_user, None)
