"""用户与认证相关的数据库模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class User(Base, TimestampMixin):
    """登录账号。

    设计取舍：
    - 只存 password_hash（bcrypt），绝不存明文；接口层也不回显该字段。
    - 用自增整型主键而非 UUID：账号表规模小，便于人工核对。
    - is_active 用于停用账号而不用物理删除，保留审计痕迹。
    - 支持两种来源：本地密码（auth_provider=local）与 Google 登录（google）。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # 仅本地账号有值；Google 账号为 NULL，此时禁止走密码登录。
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- Google 登录 ---
    # email 与 google_sub 各自唯一；email 同时作为「已有本地账号」与
    # Google 账号之间的关联键，便于后续把本地账号绑定到 Google。
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auth_provider: Mapped[str] = mapped_column(
        String(16), nullable=False, default="local", server_default="local"
    )
