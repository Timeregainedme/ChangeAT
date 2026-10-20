"""Google 登录的账号解析：按 Google profile 找到或创建本地账号。

职责边界：
    - 只处理「账号存在性/绑定」这一件事，令牌签发仍由 auth 路由统一完成；
    - 不信任前端传来的任何身份字段，入参必须是已校验过的 Google profile。

账号匹配优先级：
    1. `google_sub` 命中 → 直接复用（同一 Google 账号改名/换邮箱也能进入原账号）；
    2. `email` 命中 → 把该本地账号绑定到 Google（保留原 username 与历史数据）；
    3. 都不命中 → 新建 Google 账号。

新建账号的 username：
    取邮箱 @ 前部分并清洗为 `[a-z0-9_.-]`，若与已有 username 冲突则追加 `-2`、`-3`…
    保留 username 列的唯一性，同时让用户看得懂「这是谁」。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User

_USERNAME_MAX = 48
_USERNAME_CLEAN = re.compile(r"[^a-z0-9_.-]+")


def _username_candidates(email: str) -> list[str]:
    """从邮箱推导候选 username（第一个为「原始名」，其余为带序号的备选）。"""
    local = (email.split("@", 1)[0] or "user").strip().lower()
    base = _USERNAME_CLEAN.sub("", local) or "user"
    base = base[:_USERNAME_MAX]
    return [base] + [f"{base}-{i}" for i in range(2, 100)]


async def resolve_google_user(db: AsyncSession, profile: dict[str, Any]) -> User:
    """根据 Google profile 找到或创建账号（不提交事务，由调用方统一提交）。

    @param profile `verify_google_id_token` 的返回值（含 sub/email/name/picture）
    """
    sub = str(profile["sub"]).strip()
    email = str(profile["email"]).strip().lower()
    name = str(profile.get("name") or "").strip() or None
    picture = str(profile.get("picture") or "").strip() or None

    # 1. 已绑定过 Google：以 sub 为准，顺带刷新昵称/头像/邮箱。
    user = (await db.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    if user is not None:
        if name and name != user.display_name:
            user.display_name = name
        if picture and picture != user.avatar_url:
            user.avatar_url = picture
        if email != (user.email or ""):
            # 邮箱唯一约束：只有当新邮箱未被其他账号占用时才更新。
            taken = (
                await db.execute(select(User.id).where(User.email == email, User.id != user.id))
            ).scalar_one_or_none()
            if taken is None:
                user.email = email
        await db.flush()
        return user

    # 2. 已有本地账号使用同一邮箱：绑定 Google，保留原有 username 与数据。
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is not None:
        user.google_sub = sub
        if name and not user.display_name:
            user.display_name = name
        if picture and not user.avatar_url:
            user.avatar_url = picture
        await db.flush()
        return user

    # 3. 新建账号：password_hash 为空（禁用密码登录），auth_provider=google。
    username = None
    for candidate in _username_candidates(email):
        exists = (
            await db.execute(select(User.id).where(User.username == candidate))
        ).scalar_one_or_none()
        if exists is None:
            username = candidate
            break
    if username is None:
        # 极端情况：99 个候补都被占用，退回按邮箱哈希命名，保证一定能建号。
        username = f"user-{sub[-8:]}"

    user = User(
        username=username,
        password_hash=None,
        display_name=name or username,
        email=email,
        google_sub=sub,
        avatar_url=picture,
        auth_provider="google",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user
