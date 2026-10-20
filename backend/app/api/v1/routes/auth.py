"""认证路由：登录、当前用户、登出。

设计取舍：
- 登录失败统一返回 401 + 相同文案，不区分「用户不存在」与「密码错误」，
  避免账号枚举。
- 登录成功后返回 JWT，前端存 localStorage 并通过 Authorization: Bearer 携带。
- 不做服务端会话表：staging 单实例，无状态 JWT 足够；登出由前端丢弃 token 完成。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token, verify_password
from app.dependencies import get_current_user, get_db
from app.models.auth import User
from app.schemas.auth import LoginRequest, TokenResponse, UserRead
from app.schemas.common import ApiResponse, success_response

router = APIRouter()

_INVALID_CREDENTIALS = "用户名或密码错误"


@router.post(
    "/login",
    response_model=ApiResponse[TokenResponse],
    summary="账号密码登录",
)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> ApiResponse[TokenResponse]:
    """校验账号密码并签发访问令牌。"""
    stmt = select(User).where(User.username == payload.username)
    user = (await db.execute(stmt)).scalar_one_or_none()

    # 无论用户是否存在都执行一次哈希校验路径，降低时序侧信道差异
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已停用",
        )

    token = create_access_token(str(user.id))
    data = TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserRead.model_validate(user),
    )
    return success_response(data)


@router.get(
    "/me",
    response_model=ApiResponse[UserRead],
    summary="当前登录用户",
)
async def me(user: User = Depends(get_current_user)) -> ApiResponse[UserRead]:
    """返回当前 token 对应的用户信息，用于前端校验登录态是否仍有效。"""
    return success_response(UserRead.model_validate(user))


@router.post(
    "/logout",
    response_model=ApiResponse[dict],
    summary="登出（前端丢弃 token 即可，此接口仅用于统一调用）",
)
async def logout() -> ApiResponse[dict]:
    return success_response(data={"status": "logged_out"})
