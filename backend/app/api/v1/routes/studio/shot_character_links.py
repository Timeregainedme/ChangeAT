"""镜头-角色阵容：ShotCharacterLink 创建/更新接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.scoping import get_shot_in_workspace
from app.dependencies import WorkspaceContext, get_db, get_workspace_context
from app.schemas.common import ApiResponse, success_response
from app.schemas.studio.cast import ShotCharacterLinkCreate, ShotCharacterLinkRead
from app.services.studio.shot_character_links import (
    list_by_shot,
    upsert,
)

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[list[ShotCharacterLinkRead]],
    summary="查询镜头角色关联列表（ShotCharacterLink）",
)
async def list_shot_character_links(
    shot_id: str = Query(..., description="镜头 ID"),
    db: AsyncSession = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
) -> ApiResponse[list[ShotCharacterLinkRead]]:
    # shot_id 走 query 而非路径参数，无法用 router 级守卫，这里显式校验。
    await get_shot_in_workspace(db, shot_id, ctx)
    items = await list_by_shot(db, shot_id=shot_id)
    return success_response([ShotCharacterLinkRead.model_validate(x) for x in items])


@router.post(
    "",
    response_model=ApiResponse[ShotCharacterLinkRead],
    summary="创建/更新镜头角色关联（ShotCharacterLink）",
)
async def upsert_shot_character_link(
    body: ShotCharacterLinkCreate,
    db: AsyncSession = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
) -> ApiResponse[ShotCharacterLinkRead]:
    await get_shot_in_workspace(db, body.shot_id, ctx)
    try:
        obj = await upsert(db, body=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success_response(ShotCharacterLinkRead.model_validate(obj))
