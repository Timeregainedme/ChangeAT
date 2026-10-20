"""Google ID Token 校验。

为什么用「ID Token + tokeninfo」而不是服务端 code 交换：
    - 前端使用 Google Identity Services（GIS）按钮即可拿到 ID Token，
      不需要维护 redirect_uri、state、会话回跳等一整套 OAuth 流程；
    - 校验逻辑交给 Google 官方端点，服务端无需自行解析 JWKS 与验签，
      少一类「公钥轮换导致的登录失败」问题；
    - 代价是每次登录多一次外部请求（约 100-300ms），登录频率低，可以接受。

安全约束（缺一不可）：
    - `aud` 必须等于本应用的 client_id，防止拿别的应用的 token 登录；
    - `iss` 必须是 Google；
    - `email_verified` 必须为真，防止未验证邮箱冒用；
    - `exp` 由 Google 端点校验，过期 token 会直接返回非 200。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings

# Google 官方签发的 issuer 有两种写法，历史上都出现过。
_ALLOWED_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleTokenError(Exception):
    """ID Token 校验失败（携带可直接展示给用户的中文原因）。"""


async def verify_google_id_token(credential: str) -> dict[str, Any]:
    """校验 Google ID Token，返回 Google 返回的 profile 字段。

    @param credential 浏览器端 GIS 拿到的 `credential`（JWT 字符串）
    @throws GoogleTokenError 校验失败（token 非法/受众不符/邮箱未验证/服务不可用）
    """
    if not settings.google_client_id:
        raise GoogleTokenError("服务端未配置 GOOGLE_CLIENT_ID，无法使用 Google 登录")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                settings.google_tokeninfo_url,
                params={"id_token": credential},
            )
    except httpx.HTTPError as exc:
        raise GoogleTokenError(f"无法连接 Google 校验服务：{exc}") from exc

    if resp.status_code != 200:
        raise GoogleTokenError("Google 登录凭证无效或已过期，请重试")

    try:
        profile = resp.json()
    except ValueError as exc:
        raise GoogleTokenError("Google 校验服务返回了无法解析的内容") from exc

    if profile.get("aud") != settings.google_client_id:
        raise GoogleTokenError("该 Google 凭证不属于当前应用")

    if profile.get("iss") not in _ALLOWED_ISSUERS:
        raise GoogleTokenError("Google 凭证签发方不合法")

    if str(profile.get("email_verified", "")).lower() not in {"true", "1"}:
        raise GoogleTokenError("Google 账号邮箱未验证，无法登录")

    if not str(profile.get("email") or "").strip():
        raise GoogleTokenError("Google 未返回邮箱，无法登录")

    if not str(profile.get("sub") or "").strip():
        raise GoogleTokenError("Google 未返回用户标识，无法登录")

    return profile


def is_email_allowed(email: str) -> bool:
    """判断邮箱是否在允许名单内。

    规则：
    - 未配置 `GOOGLE_ALLOWED_EMAILS` → 放行（公网部署应显式配置，见 DEPLOY_LOG）；
    - 支持 `someone@gmail.com` 精确匹配；
    - 支持 `@example.com` 按域放行（大小写不敏感）。
    """
    allowed = settings.google_allowed_email_set
    if not allowed:
        return True
    normalized = (email or "").strip().lower()
    if normalized in allowed:
        return True
    return any(entry.startswith("@") and normalized.endswith(entry) for entry in allowed)
