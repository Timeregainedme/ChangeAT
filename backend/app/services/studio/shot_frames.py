"""镜头分镜帧服务：ShotFrameImage 的分页查询与 CRUD。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import apply_order, paginate
from app.models.studio import Chapter, Project, Shot, ShotDetail, ShotFrameImage
from app.schemas.common import ApiResponse, PaginatedData, paginated_response
from app.schemas.studio.shots import ShotFrameImageCreate, ShotFrameImageRead, ShotFrameImageUpdate
from app.services.common import (
    create_and_refresh,
    delete_if_exists,
    entity_not_found,
    flush_and_refresh,
    get_or_404,
    patch_model,
    require_entity,
)


async def list_paginated(
    db: AsyncSession,
    *,
    shot_detail_id: str | None,
    order: str | None,
    is_desc: bool,
    page: int,
    page_size: int,
    allow_fields: set[str],
    workspace_id: str | None = None,
) -> ApiResponse[PaginatedData[ShotFrameImageRead]]:
    """分页查询镜头分镜帧图片。

    `shot_detail_id` 可选，不传即全库；`workspace_id` 非空时经
    shot_details → shots → chapters → projects 过滤。
    """
    stmt = select(ShotFrameImage)
    if workspace_id is not None:
        stmt = (
            stmt.join(ShotDetail, ShotDetail.id == ShotFrameImage.shot_detail_id)
            .join(Shot, Shot.id == ShotDetail.id)
            .join(Chapter, Chapter.id == Shot.chapter_id)
            .join(Project, Project.id == Chapter.project_id)
            .where(Project.workspace_id == workspace_id)
        )
    if shot_detail_id is not None:
        stmt = stmt.where(ShotFrameImage.shot_detail_id == shot_detail_id)
    stmt = apply_order(
        stmt,
        model=ShotFrameImage,
        order=order,
        is_desc=is_desc,
        allow_fields=allow_fields,
        default="id",
    )
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)
    return paginated_response(
        [ShotFrameImageRead.model_validate(x) for x in items],
        page=page,
        page_size=page_size,
        total=total,
    )


async def create(
    db: AsyncSession,
    *,
    body: ShotFrameImageCreate,
) -> ShotFrameImage:
    """创建镜头分镜帧图片。"""
    await require_entity(db, ShotDetail, body.shot_detail_id, detail=entity_not_found("ShotDetail"), status_code=400)
    return await create_and_refresh(db, ShotFrameImage(**body.model_dump()))


async def update(
    db: AsyncSession,
    *,
    image_id: int,
    body: ShotFrameImageUpdate,
) -> ShotFrameImage:
    """更新镜头分镜帧图片。"""
    obj = await get_or_404(db, ShotFrameImage, image_id, detail=entity_not_found("ShotFrameImage"))
    patch_model(obj, body.model_dump(exclude_unset=True))
    return await flush_and_refresh(db, obj)


async def delete(
    db: AsyncSession,
    *,
    image_id: int,
) -> None:
    """删除镜头分镜帧图片。"""
    await delete_if_exists(db, ShotFrameImage, image_id)
