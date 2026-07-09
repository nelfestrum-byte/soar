from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.auth.dependencies import CurrentUser, get_current_user, require_role
from orchestrator.auth.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserOut,
)
from orchestrator.auth.service import (
    authenticate_user,
    create_access_token,
    create_api_key,
    create_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
    update_last_login,
)
from orchestrator.db.session import get_db
from sqlalchemy import select, delete
from orchestrator.auth.models import ApiKey

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    config = request.app.state.config
    if not config.auth.secret_key:
        raise HTTPException(status_code=501, detail="Authentication not configured")

    user = await authenticate_user(db, body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(
        user.id, user.role, config.auth.secret_key,
        config.auth.access_token_ttl, config.auth.algorithm,
    )
    refresh_token = await create_refresh_token(db, user.id, config.auth.refresh_token_ttl)
    await update_last_login(db, user.id)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)):
    config = request.app.state.config
    if not config.auth.secret_key:
        raise HTTPException(status_code=501, detail="Authentication not configured")

    result = await rotate_refresh_token(db, body.refresh_token, config.auth.refresh_token_ttl)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user, new_raw = result
    access_token = create_access_token(
        user.id, user.role, config.auth.secret_key,
        config.auth.access_token_ttl, config.auth.algorithm,
    )
    return TokenResponse(access_token=access_token, refresh_token=new_raw)


@router.post("/logout")
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    await revoke_refresh_token(db, body.refresh_token)
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserOut)
async def me(request: Request, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    if user.type != "user" or user.id == 0:
        raise HTTPException(status_code=403, detail="Not available for service accounts")
    from orchestrator.auth.models import User
    result = await db.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut.model_validate(db_user)


@router.post("/keys", response_model=ApiKeyCreated, dependencies=[Depends(require_role("admin"))])
async def create_key(body: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    key_obj, raw = await create_api_key(db, body.name, body.role, body.expires_at)
    base = ApiKeyOut.model_validate(key_obj)
    return ApiKeyCreated(**base.model_dump(), key=raw)


@router.get("/keys", response_model=list[ApiKeyOut], dependencies=[Depends(require_role("admin"))])
async def list_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return [ApiKeyOut.model_validate(k) for k in result.scalars()]


@router.delete("/keys/{key_id}", dependencies=[Depends(require_role("admin"))])
async def delete_key(key_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.execute(delete(ApiKey).where(ApiKey.id == key_id))
    await db.commit()
    return {"detail": "Deleted"}
