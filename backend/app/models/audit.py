"""操作审计日志。

设计取舍：
1. **只记写操作**（POST/PUT/PATCH/DELETE）。读操作占请求量九成以上，
   价值低而存储成本高；真正需要追责的是「谁改了什么、删了什么」。
2. **不记录请求体**。请求体里可能含剧本全文、提示词、以及供应商密钥
   （`providers` 的创建/更新就带着 api_key），落库等于把敏感信息复制一份。
   需要还原变更内容时，靠 `resource_type` + `resource_id` 回查业务表。
3. **失败也记录**。审计的价值恰在于知道「谁尝试删了别人的项目但被拒绝」，
   只记成功等于放走最有信息量的样本。
4. **不删除、不更新**。审计表只追加，不提供 ORM 的更新路径。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditLog(Base):
    """一条写操作审计记录。"""

    __tablename__ = "audit_logs"
    __table_args__ = (
        # 最常见的查询是「某工作区最近发生了什么」，因此按 (workspace, 时间) 建复合索引。
        Index("ix_audit_logs_ws_created", "workspace_id", "created_at"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="记录 ID"
    )

    # 可空：登录失败、鉴权前置失败等场景还没有租户上下文。
    workspace_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="所属工作区（可空：未进入租户上下文即失败）"
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="操作账号（可空：未认证或凭证无效）"
    )

    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作类型：create/update/delete/other"
    )
    method: Mapped[str] = mapped_column(String(8), nullable=False, comment="HTTP 方法")
    path: Mapped[str] = mapped_column(String(512), nullable=False, comment="请求路径（不含 query）")

    resource_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="资源类型（由路径推断，如 projects/shots）"
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="资源 ID（由路径末段推断）"
    )

    status_code: Mapped[int] = mapped_column(Integer, nullable=False, comment="响应状态码")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, comment="耗时（毫秒）")

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="客户端 IP")
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="User-Agent")
    request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="请求 ID（便于与访问日志关联）"
    )
    detail: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="补充说明（如失败原因摘要，不含敏感内容）"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
