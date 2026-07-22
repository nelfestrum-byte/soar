from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from orchestrator.auth.service import ROLES


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


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8)
    role: str = Field(default="analyst")

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError(f"role must be one of {sorted(ROLES)}")
        return v


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in ROLES:
            raise ValueError(f"role must be one of {sorted(ROLES)}")
        return v


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
