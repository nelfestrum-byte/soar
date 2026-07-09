from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    role: str = Field(default="service")
    expires_at: datetime | None = None


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    role: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyOut):
    key: str = ""
