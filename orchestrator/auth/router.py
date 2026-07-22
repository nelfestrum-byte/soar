from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser, get_current_user, require_role
from orchestrator.auth.models import ApiKey
from orchestrator.auth.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)
from orchestrator.auth.service import (
    authenticate_user,
    create_access_token,
    create_api_key,
    create_refresh_token,
    create_user,
    list_users,
    revoke_refresh_token,
    rotate_refresh_token,
    update_last_login,
    update_user,
)
from orchestrator.db.session import get_db

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


@router.post("/keys", response_model=ApiKeyCreated)
async def create_key(
    body: ApiKeyCreate, request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    key_obj, raw = await create_api_key(db, body.name, body.role, body.expires_at)
    base = ApiKeyOut.model_validate(key_obj)
    await audit_service.record(
        db, user=user, action="apikey.create", resource_type="apikey",
        resource_id=str(key_obj.id), request=request, detail={"name": body.name, "role": body.role},
    )
    return ApiKeyCreated(**base.model_dump(), key=raw)


@router.get("/keys", response_model=list[ApiKeyOut], dependencies=[Depends(require_role("admin"))])
async def list_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return [ApiKeyOut.model_validate(k) for k in result.scalars()]


@router.delete("/keys/{key_id}")
async def delete_key(
    key_id: int, request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.execute(delete(ApiKey).where(ApiKey.id == key_id))
    await db.commit()
    await audit_service.record(
        db, user=user, action="apikey.delete", resource_type="apikey",
        resource_id=str(key_id), request=request, detail={"name": key.name},
    )
    return {"detail": "Deleted"}


@router.post("/users", response_model=UserOut)
async def create_user_endpoint(
    body: UserCreate, request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        new_user = await create_user(db, body.username, body.password, body.role)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists") from None
    await audit_service.record(
        db, user=user, action="user.create", resource_type="user",
        resource_id=str(new_user.id), request=request,
        detail={"username": body.username, "role": body.role},
    )
    return UserOut.model_validate(new_user)


@router.get("/users", response_model=list[UserOut], dependencies=[Depends(require_role("admin"))])
async def list_users_endpoint(db: AsyncSession = Depends(get_db)):
    return [UserOut.model_validate(u) for u in await list_users(db)]


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user_endpoint(
    user_id: int, body: UserUpdate, request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if user_id == user.id and body.is_active is False:
        raise HTTPException(status_code=409, detail="Cannot deactivate your own account")

    try:
        updated = await update_user(
            db, user_id, role=body.role, is_active=body.is_active, password=body.password,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found") from None

    detail: dict = {}
    if body.role is not None:
        detail["role"] = body.role
    if body.is_active is not None:
        detail["is_active"] = body.is_active
    if body.password is not None:
        detail["password_reset"] = True
    await audit_service.record(
        db, user=user, action="user.update", resource_type="user",
        resource_id=str(user_id), request=request, detail=detail,
    )
    return UserOut.model_validate(updated)
