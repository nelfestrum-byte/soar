import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.auth.models import ApiKey, RefreshToken, User  # noqa: F401 — registers tables
from orchestrator.auth.service import (
    authenticate_user,
    create_refresh_token,
    create_user,
    get_user_by_id,
    list_users,
    rotate_refresh_token,
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


# ── B1: deactivation revokes live refresh-token sessions ───────────────

async def test_rotate_refresh_token_returns_none_for_inactive_user(db_session):
    user = await create_user(db_session, "alice", "pw", role="analyst")
    raw = await create_refresh_token(db_session, user.id, ttl=3600)
    await set_user_active(db_session, "alice", False)
    assert await rotate_refresh_token(db_session, raw, ttl=3600) is None


async def test_rotate_refresh_token_does_not_revoke_token_when_user_inactive(db_session):
    # set_user_active()/update_user() always mass-revoke on deactivation (see below),
    # so to isolate rotate_refresh_token()'s own is_active guard — a live token on an
    # inactive user — flip the flag directly, bypassing the service-level revoke.
    user = await create_user(db_session, "alice", "pw", role="analyst")
    raw = await create_refresh_token(db_session, user.id, ttl=3600)
    user.is_active = False
    await db_session.commit()
    await rotate_refresh_token(db_session, raw, ttl=3600)

    result = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    token = result.scalar_one()
    assert token.revoked_at is None


async def test_update_user_deactivate_revokes_all_refresh_tokens(db_session):
    user = await create_user(db_session, "alice", "pw", role="analyst")
    raw = await create_refresh_token(db_session, user.id, ttl=3600)
    await update_user(db_session, user.id, is_active=False)

    result = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    token = result.scalar_one()
    assert token.revoked_at is not None
    assert await rotate_refresh_token(db_session, raw, ttl=3600) is None


async def test_update_user_deactivate_does_not_touch_other_users_tokens(db_session):
    alice = await create_user(db_session, "alice", "pw", role="analyst")
    bob = await create_user(db_session, "bob", "pw", role="analyst")
    bob_raw = await create_refresh_token(db_session, bob.id, ttl=3600)

    await update_user(db_session, alice.id, is_active=False)

    result = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == bob.id))
    bob_token = result.scalar_one()
    assert bob_token.revoked_at is None
    assert await rotate_refresh_token(db_session, bob_raw, ttl=3600) is not None


async def test_update_user_role_change_revokes_refresh_tokens(db_session):
    user = await create_user(db_session, "alice", "pw", role="analyst")
    raw = await create_refresh_token(db_session, user.id, ttl=3600)
    await update_user(db_session, user.id, role="viewer")

    result = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    token = result.scalar_one()
    assert token.revoked_at is not None
    assert await rotate_refresh_token(db_session, raw, ttl=3600) is None


async def test_update_user_reactivate_does_not_restore_revoked_tokens(db_session):
    user = await create_user(db_session, "alice", "pw", role="analyst")
    raw = await create_refresh_token(db_session, user.id, ttl=3600)
    await update_user(db_session, user.id, is_active=False)
    await update_user(db_session, user.id, is_active=True)

    assert await rotate_refresh_token(db_session, raw, ttl=3600) is None


async def test_set_user_active_false_revokes_refresh_tokens(db_session):
    user = await create_user(db_session, "alice", "pw", role="analyst")
    raw = await create_refresh_token(db_session, user.id, ttl=3600)
    await set_user_active(db_session, "alice", False)

    result = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    token = result.scalar_one()
    assert token.revoked_at is not None
    assert await rotate_refresh_token(db_session, raw, ttl=3600) is None
