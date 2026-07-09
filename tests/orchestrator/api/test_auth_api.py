"""Auth API tests.

Uses an in-memory SQLite DB — no real PostgreSQL needed.
Uses ASGITransport (no lifespan) to avoid lifespan overwriting app.state.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.auth.models import ApiKey, RefreshToken, User  # noqa: F401 — registers tables
from orchestrator.auth.service import create_user
from orchestrator.config import AuthConfig, OrchestratorConfig
from orchestrator.db.base import Base
from orchestrator.db.session import get_db
from orchestrator.main import app

_DB_URL = "sqlite+aiosqlite:///:memory:"
_SECRET = "test-secret-key-exactly-32chars!!"


@pytest.fixture
async def db_engine():
    engine = create_async_engine(_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(db_factory):
    async with db_factory() as session:
        yield session


@pytest.fixture
def auth_config():
    cfg = OrchestratorConfig()
    cfg.auth = AuthConfig(secret_key=_SECRET)
    return cfg


@pytest.fixture
async def auth_client(db_factory, auth_config, setup_app_state):
    """AsyncClient with real auth wired, in-memory SQLite, no lifespan."""
    # Remove mock-admin override installed by the autouse setup_app_state fixture
    app.dependency_overrides.pop(get_current_user, None)

    # Wire our test DB factory instead of the app's DB
    async def _get_db():
        async with db_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db

    # Use auth-enabled config and test DB factory
    app.state.config = auth_config
    app.state.db_session_factory = db_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def admin_user(db_session):
    return await create_user(db_session, "admin", "adminpass", role="admin")


@pytest.fixture
async def analyst_user(db_session):
    return await create_user(db_session, "analyst", "analystpass", role="analyst")


@pytest.fixture
async def viewer_user(db_session):
    return await create_user(db_session, "viewer", "viewerpass", role="viewer")


# helpers

async def _login(client, username, password):
    r = await client.post("/auth/login", json={"username": username, "password": password})
    return r.json().get("access_token", "")


# ── login ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(auth_client, admin_user):
    r = await auth_client.post("/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(auth_client, admin_user):
    r = await auth_client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(auth_client):
    r = await auth_client.post("/auth/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 401


# ── me ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_me_with_valid_token(auth_client, admin_user):
    token = await _login(auth_client, "admin", "adminpass")
    r = await auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "admin"
    assert r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_me_without_token(auth_client, admin_user):
    r = await auth_client.get("/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_with_invalid_token(auth_client):
    r = await auth_client.get("/auth/me", headers={"Authorization": "Bearer bad.token.here"})
    assert r.status_code == 401


# ── refresh ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_success(auth_client, admin_user):
    r = await auth_client.post("/auth/login", json={"username": "admin", "password": "adminpass"})
    refresh_token = r.json()["refresh_token"]
    r2 = await auth_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 200
    data = r2.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["refresh_token"] != refresh_token


@pytest.mark.asyncio
async def test_refresh_token_rotation(auth_client, admin_user):
    r = await auth_client.post("/auth/login", json={"username": "admin", "password": "adminpass"})
    rt1 = r.json()["refresh_token"]
    r2 = await auth_client.post("/auth/refresh", json={"refresh_token": rt1})
    rt2 = r2.json()["refresh_token"]
    # Old token must be revoked
    r3 = await auth_client.post("/auth/refresh", json={"refresh_token": rt1})
    assert r3.status_code == 401
    # New token works
    r4 = await auth_client.post("/auth/refresh", json={"refresh_token": rt2})
    assert r4.status_code == 200


@pytest.mark.asyncio
async def test_refresh_invalid_token(auth_client):
    r = await auth_client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401


# ── logout ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout_revokes_refresh(auth_client, admin_user):
    r = await auth_client.post("/auth/login", json={"username": "admin", "password": "adminpass"})
    rt = r.json()["refresh_token"]
    await auth_client.post("/auth/logout", json={"refresh_token": rt})
    r2 = await auth_client.post("/auth/refresh", json={"refresh_token": rt})
    assert r2.status_code == 401


# ── RBAC ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_can_get_status(auth_client, viewer_user):
    token = await _login(auth_client, "viewer", "viewerpass")
    r = await auth_client.get("/status", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_post_jobs(auth_client, viewer_user):
    token = await _login(auth_client, "viewer", "viewerpass")
    r = await auth_client.post("/jobs", json={"workflow_name": "x"},
                               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_analyst_can_post_jobs(auth_client, analyst_user):
    token = await _login(auth_client, "analyst", "analystpass")
    r = await auth_client.post("/jobs", json={"workflow_name": "non_existent"},
                               headers={"Authorization": f"Bearer {token}"})
    # 404 because workflow doesn't exist, but auth passed (not 403)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_analyst_cannot_delete_workflow_code(auth_client, analyst_user):
    token = await _login(auth_client, "analyst", "analystpass")
    r = await auth_client.delete("/workflows/test/code",
                                 headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_access_transfer(auth_client, admin_user):
    token = await _login(auth_client, "admin", "adminpass")
    r = await auth_client.post("/transfer/export", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_access_transfer(auth_client, viewer_user):
    token = await _login(auth_client, "viewer", "viewerpass")
    r = await auth_client.post("/transfer/export",
                               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


# ── API keys ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_use_api_key(auth_client, admin_user):
    token = await _login(auth_client, "admin", "adminpass")
    r = await auth_client.post("/auth/keys",
                               json={"name": "test-service", "role": "service"},
                               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert "key" in data
    assert data["key"].startswith("soar_")
    api_key = data["key"]

    r2 = await auth_client.get("/status", headers={"Authorization": f"Bearer {api_key}"})
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_service_key_cannot_delete_workflow(auth_client, admin_user):
    token = await _login(auth_client, "admin", "adminpass")
    r = await auth_client.post("/auth/keys",
                               json={"name": "svc", "role": "service"},
                               headers={"Authorization": f"Bearer {token}"})
    api_key = r.json()["key"]

    r2 = await auth_client.delete("/workflows/test/code",
                                  headers={"Authorization": f"Bearer {api_key}"})
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_list_keys(auth_client, admin_user):
    token = await _login(auth_client, "admin", "adminpass")
    await auth_client.post("/auth/keys", json={"name": "k1", "role": "service"},
                           headers={"Authorization": f"Bearer {token}"})
    r = await auth_client.get("/auth/keys", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_delete_key(auth_client, admin_user):
    token = await _login(auth_client, "admin", "adminpass")
    cr = await auth_client.post("/auth/keys", json={"name": "to-delete", "role": "service"},
                                headers={"Authorization": f"Bearer {token}"})
    key_id = cr.json()["id"]
    api_key = cr.json()["key"]

    await auth_client.delete(f"/auth/keys/{key_id}", headers={"Authorization": f"Bearer {token}"})

    r = await auth_client.get("/status", headers={"Authorization": f"Bearer {api_key}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_viewer_cannot_create_key(auth_client, admin_user, viewer_user):
    viewer_token = await _login(auth_client, "viewer", "viewerpass")
    r = await auth_client.post("/auth/keys", json={"name": "x", "role": "service"},
                               headers={"Authorization": f"Bearer {viewer_token}"})
    assert r.status_code == 403
