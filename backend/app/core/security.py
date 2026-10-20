"""认证基础设施：密码哈希与 JWT 签发/校验。

设计取舍：
- 密码用 bcrypt（自带盐、抗 GPU 暴力），不存明文、不做可逆加密。
- JWT 用 HS256（单机 staging 足够）；密钥从 settings 读取，未配置时拒绝启动，
  避免「用默认密钥签发 token」这种可被伪造的安全事故。
- 只放「纯函数」，不依赖数据库和 FastAPI，便于单测与被路由/依赖复用。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import HTTPException, status

from app.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """把明文密码哈希为可入库的字符串。"""
    if not password:
        raise ValueError("password must not be empty")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配。

    任何异常（哈希格式非法等）一律视为不匹配，避免把内部错误暴露成 500。
    """
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, *, expires_minutes: int | None = None) -> str:
    """签发访问令牌。

    subject 用用户主键（字符串），同时写入 sub 与 username 之外的只读声明，
    避免在 token 里塞敏感信息（token 只签名不加密，前端可解码）。
    """
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET 未配置，拒绝签发 token")

    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """解析并校验令牌；失败统一抛 401，不区分「过期/伪造」以免泄露信息。"""
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET 未配置，拒绝校验 token")
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态无效或已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc