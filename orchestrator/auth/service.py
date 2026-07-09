import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.auth.models import ApiKey, RefreshToken, User

ROLES = {"admin", "analyst", "viewer", "service"}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_access_token(user_id: int, role: str, secret_key: str, ttl: int, algorithm: str) -> str:
    expire = datetime.now(UTC) + timedelta(seconds=ttl)
    payload = {"sub": str(user_id), "role": role, "type": "user", "exp": expire}
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(token: str, secret_key: str, algorithm: str) -> dict | None:
    try:
        return jwt.decode(token, secret_key, algorithms=[algorithm])
    except JWTError:
        return None


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username, User.is_active == True))  # noqa: E712
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


async def create_refresh_token(db: AsyncSession, user_id: int, ttl: int) -> str:
    raw = secrets.token_urlsafe(48)
    token = RefreshToken(
        user_id=user_id,
        token_hash=_token_hash(raw),
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
    )
    db.add(token)
    await db.commit()
    return raw


async def rotate_refresh_token(
    db: AsyncSession, raw_token: str, ttl: int
) -> tuple[User, str] | None:
    """Revoke old refresh token and issue a new one. Returns (user, new_raw_token) or None."""
    h = _token_hash(raw_token)
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == h, RefreshToken.revoked_at == None)  # noqa: E711
        .with_for_update()
    )
    token = result.scalar_one_or_none()
    if not token:
        return None
    if token.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        return None

    token.revoked_at = datetime.now(UTC)

    new_raw = secrets.token_urlsafe(48)
    new_token = RefreshToken(
        user_id=token.user_id,
        token_hash=_token_hash(new_raw),
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
    )
    db.add(new_token)

    user_result = await db.execute(select(User).where(User.id == token.user_id))
    user = user_result.scalar_one_or_none()

    await db.commit()
    return user, new_raw


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> bool:
    h = _token_hash(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == h, RefreshToken.revoked_at == None)  # noqa: E711
    )
    token = result.scalar_one_or_none()
    if not token:
        return False
    token.revoked_at = datetime.now(UTC)
    await db.commit()
    return True


async def get_api_key(db: AsyncSession, raw_token: str) -> ApiKey | None:
    h = _token_hash(raw_token)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == h, ApiKey.is_active == True)  # noqa: E712
    )
    key = result.scalar_one_or_none()
    if not key:
        return None
    if key.expires_at and key.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        return None
    key.last_used_at = datetime.now(UTC)
    await db.commit()
    return key


async def create_api_key(
    db: AsyncSession, name: str, role: str, expires_at: datetime | None
) -> tuple[ApiKey, str]:
    raw = "soar_" + secrets.token_hex(32)
    prefix = raw[:12]
    key = ApiKey(
        name=name,
        key_prefix=prefix,
        key_hash=_token_hash(raw),
        role=role,
        expires_at=expires_at,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key, raw


async def create_user(
    db: AsyncSession, username: str, password: str, role: str = "analyst"
) -> User:
    user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_last_login(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.last_login_at = datetime.now(UTC)
        await db.commit()
