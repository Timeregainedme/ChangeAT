"""认证相关的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """账号密码登录请求。"""

    username: str = Field(min_length=1, max_length=64, description="登录名")
    password: str = Field(min_length=1, max_length=256, description="明文密码（仅传输，不落库）")


class UserRead(BaseModel):
    """对外暴露的用户信息（不含 password_hash）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None = None
    is_active: bool
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    """登录成功后的令牌与用户信息。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="有效期（秒）")
    user: UserRead
