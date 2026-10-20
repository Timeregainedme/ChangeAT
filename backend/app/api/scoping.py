"""工作区数据隔离：按 ID 读取业务实体时的统一入口。

存在意义：
多租户最危险的失败模式不是「拒绝访问」，而是**忘了过滤**——路由拿到一个
全局唯一的 `project_id` 就直接 `db.get()`，于是任何登录用户都能读到别家工作区
的数据。因此本模块只提供「带 workspace 条件」的读取函数，路由里不再直接
`db.get(Project, id)` 取业务实体。

返回语义：
- 实体不存在，或存在但不属于当前工作区 → 一律 404（`{Entity} not found`）。
  刻意不返回 403：403 会告诉调用方「这个 ID 是真的，只是你没权限」，
  等于把其他租户的资源 ID 暴露成可探测的枚举面。
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import WorkspaceContext
from app.models.studio import Chapter, Project, Shot
from app.services.common import entity_not_found


async def get_project_in_workspace(
    db: AsyncSession,
    project_id: str,
    ctx: WorkspaceContext,
) -> Project:
    """读取项目并校验工作区归属。"""
    obj = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.workspace_id == ctx.workspace_id,
        )
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("Project"),
        )
    return obj


async def get_chapter_in_workspace(
    db: AsyncSession,
    chapter_id: str,
    ctx: WorkspaceContext,
) -> Chapter:
    """读取章节并校验归属。

    章节没有 workspace_id 列，归属经由 project 间接确定；用 join 而不是
    「先读章节、再读项目」两跳，避免多一次往返，也避免两步之间数据变更导致校验错位。
    """
    obj = await db.scalar(
        select(Chapter)
        .join(Project, Project.id == Chapter.project_id)
        .where(
            Chapter.id == chapter_id,
            Project.workspace_id == ctx.workspace_id,
        )
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("Chapter"),
        )
    return obj


async def get_shot_in_workspace(
    db: AsyncSession,
    shot_id: str,
    ctx: WorkspaceContext,
) -> Shot:
    """读取镜头并校验归属（shot → chapter → project → workspace）。"""
    obj = await db.scalar(
        select(Shot)
        .join(Chapter, Chapter.id == Shot.chapter_id)
        .join(Project, Project.id == Chapter.project_id)
        .where(
            Shot.id == shot_id,
            Project.workspace_id == ctx.workspace_id,
        )
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("Shot"),
        )
    return obj


def apply_workspace_filter(stmt, ctx: WorkspaceContext):
    """给针对 `projects` 的查询追加工作区条件。

    列表类路由用 `select(Project)` 起步时，务必套一层本函数；
    漏掉它的表现是「能搜到别家项目名」，不会报错，所以必须靠约定而非报错兜住。
    """
    return stmt.where(Project.workspace_id == ctx.workspace_id)


def apply_chapter_workspace_filter(stmt, ctx: WorkspaceContext):
    """给针对 `chapters` 的查询追加工作区条件（经 project 归属）。

    只适用于 `select(Chapter)` 起步且尚未 join projects 的语句；
    已经 join 过的语句直接追加 `Project.workspace_id == ...` 即可，避免重复 join。
    """
    return stmt.join(Project, Project.id == Chapter.project_id).where(
        Project.workspace_id == ctx.workspace_id
    )
