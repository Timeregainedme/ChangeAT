"""创建/重置管理员账号（幂等）。

用法：
    cd backend && .venv/bin/python init_admin.py
    # 或在容器内：uv run python init_admin.py

可通过环境变量覆盖默认值：
    ADMIN_USERNAME（默认 admin）
    ADMIN_PASSWORD（默认 admin123）

安全说明：
    默认密码仅用于 staging 首次登录。生产环境务必：
      1. 首次登录后立即修改密码；
      2. 或在本脚本运行前设置 ADMIN_PASSWORD 为强密码。
    脚本不会把密码写进日志。
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from app.core.db import close_db, init_db
from app.core.security import hash_password
from app.models.auth import User
from app.core.db import async_session_maker


async def _main() -> None:
    username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    password = os.getenv("ADMIN_PASSWORD", "admin123")

    # 确保所有表存在（含 users；models 包已导入 User 模型）
    await init_db()

    async with async_session_maker() as session:
        existing = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    display_name="管理员",
                    is_active=True,
                )
            )
            await session.commit()
            print(f"[ok] 已创建管理员账号 username={username}")
        else:
            # 已存在则重置密码，便于运维找回（不新建重复账号）
            existing.password_hash = hash_password(password)
            existing.is_active = True
            await session.commit()
            print(f"[ok] 已重置管理员密码 username={username}")

    await close_db()
    print()
    print("登录信息：")
    print(f"  username = {username}")
    print("  password = ******（你设置的那个，本脚本不回显）")
    print()
    print("提示：默认口令强度很弱，请登录后尽快修改。")


if __name__ == "__main__":
    asyncio.run(_main())