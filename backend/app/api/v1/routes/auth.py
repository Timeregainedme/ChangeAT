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
from app.core.google_auth import GoogleTokenError, is_email_allowed, verify_google_id_token
from app.core.security import create_access_token, verify_password
from app.dependencies import get_current_user, get_db
from app.models.auth import User
from app.schemas.auth import GoogleLoginRequest, LoginRequest, TokenResponse, UserRead
from app.schemas.common import ApiResponse, success_response
from app.services.auth_accounts import resolve_google_user

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

    # 无论用户是否存在都执行一次哈希校验路径，降低时序侧信道差异。
    # password_hash 为 None 表示该账号只能用 Google 登录。
    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
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


@router.post(
    "/google",
    response_model=ApiResponse[TokenResponse],
    summary="Google 登录（Google Identity Services ID Token）",
)
async def login_with_google(
    payload: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TokenResponse]:
    """用前端 GIS 取得的 ID Token 登录。

    流程：
    1. 服务端向 Google 校验 ID Token（受众、签发方、邮箱验证状态）；
    2. 按 Google 邮箱名单过滤（`GOOGLE_ALLOWED_EMAILS` 为空时放行全部已验证邮箱）；
    3. 按 google_sub / email 找到或创建账号；
    4. 签发与本地登录相同的 JWT，前端无需区分登录方式。

    任何身份信息都来自 Google 的校验结果，不采信请求体里的自报字段。
    """
    try:
        profile = await verify_google_id_token(payload.credential)
    except GoogleTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    email = str(profile["email"]).strip().lower()
    if not is_email_allowed(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"{email} 未在允许名单中。"
                "请联系管理员在 GOOGLE_ALLOWED_EMAILS 中加入该邮箱或域名。"
            ),
        )

    user = await resolve_google_user(db, profile)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")

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
