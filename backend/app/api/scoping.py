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

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import WorkspaceContext, get_db, get_workspace_context
from app.models.studio import (
    Actor,
    Chapter,
    Character,
    Costume,
    Project,
    ProjectActorLink,
    ProjectCostumeLink,
    ProjectPropLink,
    ProjectSceneLink,
    Prop,
    Scene,
    Shot,
    ShotDetail,
    ShotDialogLine,
    ShotFrameImage,
)
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


async def get_entity_in_workspace(
    db: AsyncSession,
    entity_id: str,
    ctx: WorkspaceContext,
    *,
    entity_type: str | None = None,
):
    """校验资产实体（actor/character/scene/prop/costume）归属。

    统一实体路由用 `/{entity_type}/{entity_id}` 表达五种资产，路径里没有独立段
    能区分表名，因此按表逐个探测。

    归属链分两类（这一点很容易搞错）：
    - `Character` 是项目内资产，自身直接持有 `project_id`；
    - `Scene` / `Prop` / `Costume` / `Actor` 是**全局资产**，可跨项目复用，
      自身没有 `project_id`，归属经 `project_{scene,prop,costume,actor}_links` 确定。

    对全局资产一律用「任一关联项目属于当前工作区即放行」的语义：
    同一场景被两个工作区的项目引用时，两个工作区都能看到它，但都改不到对方的关联。
    """
    character = await db.scalar(
        select(Character)
        .join(Project, Project.id == Character.project_id)
        .where(Character.id == entity_id, Project.workspace_id == ctx.workspace_id)
    )
    if character is not None:
        return character

    for model, link_model, link_field in _GLOBAL_ASSET_LINKS:
        obj = await db.scalar(
            select(model)
            .join(link_model, getattr(link_model, link_field) == model.id)
            .join(Project, Project.id == link_model.project_id)
            .where(model.id == entity_id, Project.workspace_id == ctx.workspace_id)
        )
        if obj is not None:
            return obj

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        # 文案沿用实体名：`/entities/actor/{id}` 不存在时回 "Actor not found"，
        # 与改造前一致，前端不需要为新文案做适配。
        detail=entity_not_found((entity_type or "Entity").capitalize()),
    )


# 「全局资产 → 项目关联表 → 外键字段」的映射，供归属校验与列表过滤共用。
_GLOBAL_ASSET_LINKS: tuple[tuple[object, object, str], ...] = (
    (Scene, ProjectSceneLink, "scene_id"),
    (Prop, ProjectPropLink, "prop_id"),
    (Costume, ProjectCostumeLink, "costume_id"),
    (Actor, ProjectActorLink, "actor_id"),
)


async def get_shot_detail_in_workspace(
    db: AsyncSession,
    shot_id: str,
    ctx: WorkspaceContext,
) -> ShotDetail:
    """读取镜头细节并校验归属。

    `shot_details` 与 `shots` 共享主键，所以路径里的 shot_id 可直接用于查细节；
    返回细节对象而非镜头，是为了让「不存在」的文案保持 `ShotDetail not found`，
    与既有接口语义一致（前端与测试都依赖这条文案）。
    """
    obj = await db.scalar(
        select(ShotDetail)
        .join(Shot, Shot.id == ShotDetail.id)
        .join(Chapter, Chapter.id == Shot.chapter_id)
        .join(Project, Project.id == Chapter.project_id)
        .where(
            ShotDetail.id == shot_id,
            Project.workspace_id == ctx.workspace_id,
        )
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("ShotDetail"),
        )
    return obj


async def get_dialog_line_in_workspace(
    db: AsyncSession,
    line_id: str,
    ctx: WorkspaceContext,
):
    """校验台词行归属。

    多跳链路：shot_dialog_lines.shot_detail_id → shot_details.id → shots.id
    → chapters.id → projects.workspace_id。
    注意 `shot_details` 与 `shots` 共享主键，所以 shot_detail_id 实际就是 shot_id，
    但仍显式 join 两次，避免未来解除共享主键时这条链路静默失效。
    """
    obj = await db.scalar(
        select(ShotDialogLine)
        .join(ShotDetail, ShotDetail.id == ShotDialogLine.shot_detail_id)
        .join(Shot, Shot.id == ShotDetail.id)
        .join(Chapter, Chapter.id == Shot.chapter_id)
        .join(Project, Project.id == Chapter.project_id)
        .where(
            ShotDialogLine.id == _as_int(line_id),
            Project.workspace_id == ctx.workspace_id,
        )
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("ShotDialogLine"),
        )
    return obj


async def get_frame_image_in_workspace(
    db: AsyncSession,
    image_id: str,
    ctx: WorkspaceContext,
):
    """校验分镜帧图归属（shot_frame_images.shot_detail_id → shots）。"""
    obj = await db.scalar(
        select(ShotFrameImage)
        .join(ShotDetail, ShotDetail.id == ShotFrameImage.shot_detail_id)
        .join(Shot, Shot.id == ShotDetail.id)
        .join(Chapter, Chapter.id == Shot.chapter_id)
        .join(Project, Project.id == Chapter.project_id)
        .where(
            ShotFrameImage.id == _as_int(image_id),
            Project.workspace_id == ctx.workspace_id,
        )
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("ShotFrameImage"),
        )
    return obj


async def get_shot_link_in_workspace(
    db: AsyncSession,
    link_id: str,
    ctx: WorkspaceContext,
):
    """校验「项目 ↔ 资产」关联行归属。

    四种关联表（actor/scene/prop/costume）共享同一套 `link_id` 路径参数，
    路由前缀只区分业务语义、不构成独立路径段，因此这里按表逐个探测。
    探测成本是低频写操作上的 1~4 次主键查询，可接受；
    换来的是不必在路由层重复声明四份守卫。
    """
    numeric_id = _as_int(link_id)
    for model in (ProjectActorLink, ProjectSceneLink, ProjectPropLink, ProjectCostumeLink):
        obj = await db.scalar(
            select(model)
            .join(Project, Project.id == model.project_id)
            .where(model.id == numeric_id, Project.workspace_id == ctx.workspace_id)
        )
        if obj is not None:
            return obj
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=entity_not_found("ShotLink"),
    )


def _as_int(raw: str) -> int:
    """把路径里的数字 ID 转 int；非法值直接 404，不抛 500。"""
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("Resource"),
        ) from exc


# 写方法集合：用于 router 级守卫按 HTTP 方法区分读/写权限。
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def require_scoped_resource(param: str, resolver):
    """生成 router 级守卫依赖：校验路径参数指向的资源属于当前工作区。

    为什么挂在 router 而不是逐个端点：
    `shots` 有 23 个端点、`entities` 有 11 个，逐个加依赖时漏掉一个就是一个越权口子，
    而且新增端点时很容易忘记补。router 级守卫让「新端点默认受保护」。

    行为：
    - 路径里没有该参数（如列表接口 `""`、`/runtime-summary`）→ 跳过归属校验，
      列表本身的工作区过滤由各自 service 负责；
    - 有该参数 → 调用 resolver 做归属校验，不通过抛 404；
    - 写方法（POST/PUT/PATCH/DELETE）额外要求 editor 及以上，
      防止 viewer（外部审片账号）触发写操作或消耗额度的生成任务。

    参数：
    - `param`：路径参数名，如 `shot_id`；
    - `resolver`：形如 `(db, resource_id, ctx) -> object` 的协程，负责实际校验。
    """

    async def _guard(
        request: Request,
        db: AsyncSession = Depends(get_db),
        ctx: WorkspaceContext = Depends(get_workspace_context),
    ) -> None:
        if request.method in WRITE_METHODS and not ctx.can_write:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"当前角色（{ctx.role.value}）无写权限，至少需要 editor",
            )
        resource_id = request.path_params.get(param)
        if not resource_id:
            return
        await resolver(db, resource_id, ctx)

    return _guard
