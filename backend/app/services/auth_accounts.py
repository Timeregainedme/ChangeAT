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

关于 `refresh`：
    `created_at` / `updated_at` 由数据库 `server_default=func.now()` 生成，
    INSERT/UPDATE 之后这两个属性处于「未加载」状态；若紧接着用 Pydantic
    从 ORM 对象取字段（同步上下文），会触发惰性加载并抛 MissingGreenlet。
    因此所有路径在返回前统一 `await db.refresh(user)`，把服务端生成的列读回来。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User

_USERNAME_MAX = 48
_USERNAME_CLEAN = re.compile(r"[^a-z0-9_.-]+")

# 用户名候选上限：足够覆盖「同邮箱前缀大量重复」的极端场景。
_USERNAME_MAX_SUFFIX = 100


def _username_candidates(email: str) -> list[str]:
    """从邮箱推导候选 username（第一个为「原始名」，其余为带序号的备选）。"""
    local = (email.split("@", 1)[0] or "user").strip().lower()
    base = _USERNAME_CLEAN.sub("", local) or "user"
    base = base[:_USERNAME_MAX]
    return [base] + [f"{base}-{i}" for i in range(2, _USERNAME_MAX_SUFFIX)]


async def _find_by_sub(db: AsyncSession, sub: str) -> User | None:
    return (await db.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()


async def _find_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def _is_username_taken(db: AsyncSession, username: str) -> bool:
    return (
        await db.execute(select(User.id).where(User.username == username))
    ).scalar_one_or_none() is not None


async def resolve_google_user(db: AsyncSession, profile: dict[str, Any]) -> User:
    """根据 Google profile 找到或创建账号（不提交事务，由调用方统一提交）。

    @param profile `verify_google_id_token` 的返回值（含 sub/email/name/picture）
    """
    sub = str(profile["sub"]).strip()
    email = str(profile["email"]).strip().lower()
    name = str(profile.get("name") or "").strip() or None
    picture = str(profile.get("picture") or "").strip() or None

    user: User | None = None

    # --- 1. 已绑定过 Google：以 sub 为准，顺带刷新昵称/头像/邮箱 ---
    user = await _find_by_sub(db, sub)
    if user is not None:
        if name and name != user.display_name:
            user.display_name = name
        if picture and picture != user.avatar_url:
            user.avatar_url = picture
        if email != (user.email or ""):
            # 邮箱唯一约束：只有当新邮箱未被其他账号占用时才更新。
            if await _find_by_email(db, email) is None:
                user.email = email
        await db.flush()
        await db.refresh(user)
        return user

    # --- 2. 已有本地账号使用同一邮箱：绑定 Google，保留原有 username 与数据 ---
    user = await _find_by_email(db, email)
    if user is not None:
        user.google_sub = sub
        if name and not user.display_name:
            user.display_name = name
        if picture and not user.avatar_url:
            user.avatar_url = picture
        # 保留原 auth_provider：本地账号绑定 Google 后仍可用密码登录。
        await db.flush()
        await db.refresh(user)
        return user

    # --- 3. 新建账号：password_hash 为空（禁用密码登录），auth_provider=google ---
    username: str | None = None
    for candidate in _username_candidates(email):
        if not await _is_username_taken(db, candidate):
            username = candidate
            break
    if username is None:
        # 极端情况：候补全部被占用，退回按 sub 命名，保证一定能建号。
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
    # created_at / updated_at 由数据库生成，刷回后才能安全地转成 UserRead。
    await db.refresh(user)
    return user
