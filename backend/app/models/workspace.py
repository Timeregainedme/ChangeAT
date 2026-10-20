"""工作区与成员模型：多租户的数据边界。

设计取舍：
1. **workspace 是最粗的资源边界**，project 直接挂 workspace，章节/镜头/资产通过
   project 间接归属。这样 `workspace_id` 只需出现在 projects 与少量全局表上，
   不必给 54 张表逐一加列。
2. **角色写在成员表里，不建 roles/permissions 两张表**：理由见
   `app/models/types.py::WorkspaceRole` 的注释。
3. **不删除成员行，只置 `is_active=False`**：保留审计痕迹，避免历史操作记录
   中出现的 user_id 变成悬空引用。
4. `owner_id` 用 `RESTRICT` 而非 `CASCADE`：工作区是有价值的业务容器，不允许
   因为误删账号而连带删除全部项目。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.types import WorkspaceRole

if TYPE_CHECKING:
    from app.models.auth import User
    from app.models.studio_projects import Project


class Workspace(Base, TimestampMixin):
    """工作区（租户）。所有业务数据的顶层归属。"""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="工作区 ID")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="工作区名称")
    # slug 供 URL/日志使用，便于人工识别；不参与鉴权判定。
    slug: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, comment="URL 友好标识（唯一）"
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="工作区简介"
    )
    # RESTRICT：工作区不允许因账号删除而消失。
    owner_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="所有者（创建者）",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否启用（停用工作区不删数据）"
    )

    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkspaceMember.id",
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="workspace",
        order_by="Project.id",
    )
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])


class WorkspaceMember(Base, TimestampMixin):
    """工作区成员及其角色。

    唯一约束 `(workspace_id, user_id)` 保证同一用户在同一工作区只有一条成员记录；
    角色变更走 UPDATE，不新增行 —— 否则鉴权时无法确定以哪条为准。
    """

    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_ws_user"),
        Index("ix_workspace_members_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="成员记录 ID"
    )
    workspace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属工作区",
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="成员账号",
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        String(16),
        nullable=False,
        default=WorkspaceRole.editor,
        server_default=WorkspaceRole.editor.value,
        comment="角色：owner/admin/editor/viewer",
    )
    # 退出成员用置 false 表达，保留行以便历史操作记录可追溯。
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否为在岗成员"
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
