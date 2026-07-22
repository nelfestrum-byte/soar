import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.auth.models import ApiKey, RefreshToken, User  # noqa: F401 — registers tables
from orchestrator.auth.service import (
    authenticate_user,
    create_user,
    get_user_by_id,
    list_users,
    set_user_active,
    update_user,
)
from orchestrator.db.base import Base

_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session():
    engine = create_async_engine(_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def test_deactivate_user_sets_is_active_false(db_session):
    await create_user(db_session, "alice", "pw", role="analyst")
    user = await set_user_active(db_session, "alice", False)
    assert user.is_active is False


async def test_activate_user_sets_is_active_true(db_session):
    await create_user(db_session, "alice", "pw", role="analyst")
    await set_user_active(db_session, "alice", False)
    user = await set_user_active(db_session, "alice", True)
    assert user.is_active is True


async def test_set_user_active_unknown_username_raises(db_session):
    with pytest.raises(LookupError):
        await set_user_active(db_session, "ghost", False)


async def test_deactivated_user_cannot_authenticate(db_session):
    await create_user(db_session, "alice", "pw", role="analyst")
    await set_user_active(db_session, "alice", False)
    assert await authenticate_user(db_session, "alice", "pw") is None


# ── list_users / get_user_by_id / update_user ──────────────────────────

async def test_list_users_returns_all(db_session):
    await create_user(db_session, "alice", "pw", role="analyst")
    await create_user(db_session, "bob", "pw", role="viewer")
    users = await list_users(db_session)
    assert {u.username for u in users} == {"alice", "bob"}


async def test_get_user_by_id_unknown_returns_none(db_session):
    assert await get_user_by_id(db_session, 999) is None


async def test_update_user_role(db_session):
    user = await create_user(db_session, "alice", "pw", role="viewer")
    updated = await update_user(db_session, user.id, role="admin")
    assert updated.role == "admin"


async def test_update_user_is_active(db_session):
    user = await create_user(db_session, "alice", "pw", role="analyst")
    updated = await update_user(db_session, user.id, is_active=False)
    assert updated.is_active is False
    assert await authenticate_user(db_session, "alice", "pw") is None


async def test_update_user_password_reset(db_session):
    user = await create_user(db_session, "alice", "oldpw", role="analyst")
    await update_user(db_session, user.id, password="newpw")
    assert await authenticate_user(db_session, "alice", "oldpw") is None
    assert await authenticate_user(db_session, "alice", "newpw") is not None


async def test_update_user_no_fields_is_noop(db_session):
    user = await create_user(db_session, "alice", "pw", role="analyst")
    updated = await update_user(db_session, user.id)
    assert updated.role == "analyst"
    assert updated.is_active is True


async def test_update_user_unknown_id_raises(db_session):
    with pytest.raises(LookupError):
        await update_user(db_session, 999, role="admin")
