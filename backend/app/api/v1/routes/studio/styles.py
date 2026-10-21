"""风格目录路由。

挂在 `/api/v1/studio/styles` 下：列出、新增、修改、删除风格。
列表同时被「项目设置 / 新建项目」使用，所以读接口不做分页——
风格是低频小集合（十几条），分页只会增加前端复杂度。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.common import ApiResponse, success_response
from app.schemas.studio.projects import (
    ProjectStyleOptionCreate,
    ProjectStyleOptionRead,
    ProjectStyleOptionUpdate,
)
from app.services.studio.style_catalog import (
    create_style_option,
    delete_style_option,
    list_style_options,
    update_style_option,
)

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[list[ProjectStyleOptionRead]],
    summary="列出风格目录",
)
async def list_styles(db: AsyncSession = Depends(get_db)) -> ApiResponse[list[ProjectStyleOptionRead]]:
    rows = await list_style_options(db)
    await db.commit()
    return success_response([ProjectStyleOptionRead.model_validate(row) for row in rows])


@router.post(
    "",
    response_model=ApiResponse[ProjectStyleOptionRead],
    summary="新增风格",
)
async def create_style(
    body: ProjectStyleOptionCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProjectStyleOptionRead]:
    try:
        row = await create_style_option(
            db,
            visual_style=body.visual_style,
            name=body.name,
            description=body.description,
            prompt_pack=body.prompt_pack,
            sort_order=body.sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    return success_response(ProjectStyleOptionRead.model_validate(row))


@router.patch(
    "/{style_id}",
    response_model=ApiResponse[ProjectStyleOptionRead],
    summary="修改风格",
)
async def update_style(
    style_id: str,
    body: ProjectStyleOptionUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProjectStyleOptionRead]:
    try:
        row = await update_style_option(
            db,
            style_id=style_id,
            name=body.name,
            description=body.description,
            prompt_pack=body.prompt_pack,
            sort_order=body.sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    return success_response(ProjectStyleOptionRead.model_validate(row))


@router.delete(
    "/{style_id}",
    response_model=ApiResponse[None],
    summary="删除风格",
)
async def delete_style(style_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[None]:
    try:
        await delete_style_option(db, style_id=style_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await db.commit()
    return success_response(None)
