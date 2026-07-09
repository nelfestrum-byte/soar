from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.auth.service import decode_access_token, get_api_key


@dataclass
class CurrentUser:
    id: int
    role: str
    type: str  # "user" | "service"
    username: str = ""


async def get_current_user(request: Request) -> CurrentUser:
    config = request.app.state.config

    # Auth disabled when secret_key is not configured — return anonymous admin
    if not config.auth.secret_key:
        return CurrentUser(id=0, role="admin", type="user", username="anonymous")

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization[7:]

    # Try JWT first — no DB needed
    payload = decode_access_token(token, config.auth.secret_key, config.auth.algorithm)
    if payload and payload.get("type") == "user":
        return CurrentUser(
            id=int(payload["sub"]),
            role=payload.get("role", "viewer"),
            type="user",
        )

    # Try API key — needs DB session
    factory = getattr(request.app.state, "db_session_factory", None)
    if factory is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    async with factory() as db:
        key = await get_api_key(db, token)
        if key:
            return CurrentUser(id=key.id, role=key.role, type="service", username=key.name)

    raise HTTPException(status_code=401, detail="Invalid credentials")


def require_role(*roles: str):
    """Returns a FastAPI dependency that enforces role membership."""
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return _check
