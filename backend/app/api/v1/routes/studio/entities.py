"""统一实体 CRUD：actor/character/scene/prop/costume。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.scoping import get_entity_in_workspace
from app.dependencies import WorkspaceContext, get_db, get_workspace_context
from app.schemas.common import ApiResponse, PaginatedData, created_response, empty_response, paginated_response, success_response
from app.schemas.studio.entity_existence import (
    EntityNameExistenceCheckRequest,
    EntityNameExistenceCheckResponse,
)
from app.schemas.studio.entity_merge import EntityMergeRequest, EntityMergePairResult
from app.services.studio import StudioEntitiesService
from app.services.studio.entity_merge import merge_entities

router = APIRouter()


async def _require_entity_in_workspace(
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
) -> None:
    """统一实体路由的守卫：按 `/{entity_type}/{entity_id}` 校验归属。

    之所以不复用通用工厂 `require_scoped_resource`：这里需要把 `entity_type`
    一并传给 resolver，才能生成与改造前一致的「Actor not found / Scene not found」
    文案，而不是笼统的「Entity not found」。
    """
    entity_id = request.path_params.get("entity_id")
    if not entity_id:
        return
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not ctx.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"当前角色（{ctx.role.value}）无写权限，至少需要 editor",
        )
    await get_entity_in_workspace(
        db,
        entity_id,
        ctx,
        entity_type=request.path_params.get("entity_type"),
    )


router.dependencies.append(Depends(_require_entity_in_workspace))


@router.post(
    "/existence-check",
    response_model=ApiResponse[EntityNameExistenceCheckResponse],
    summary="批量检测资产名称是否存在（模糊匹配，不分页）",
)
async def check_entity_names_existence(
    body: EntityNameExistenceCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EntityNameExistenceCheckResponse]:
    service = StudioEntitiesService(db)
    data = await service.check_names_existence(
        project_id=body.project_id,
        shot_id=body.shot_id,
        character_names=body.character_names,
        prop_names=body.prop_names,
        scene_names=body.scene_names,
        costume_names=body.costume_names,
    )
    return success_response(EntityNameExistenceCheckResponse.model_validate(data))


@router.post(
    "/{entity_type}/merge",
    response_model=ApiResponse[EntityMergePairResult],
    summary="合并两个同类型实体（数据库层，把 source 并入 target）",
)
async def merge_entity_pair(
    entity_type: str,
    body: EntityMergeRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EntityMergePairResult]:
    """把 `source_id` 合并进 `target_id`，返回迁移统计。

    行为：
    - 图片、关联、提取候选全部迁移到 target；
    - target 已在同一作用域有关联时删除 source 的重复关联（避免唯一约束冲突）；
    - 成功后删除 source 记录；任何失败整体回滚（事务由 `get_db` 统一提交/回滚）。

    典型用途：资产页发现「护工工作服」与「护工护理工作服」是同一种服装时，
    把其中一个合并到另一个，避免后续镜头重复引用两套资产。
    """
    try:
        payload = await merge_entities(
            db,
            entity_type=entity_type,
            source_id=body.source_id,
            target_id=body.target_id,
        )
    except ValueError as exc:
        # 类型不支持、自合并等请求级错误统一 400，便于前端直接展示原文。
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return success_response(EntityMergePairResult.model_validate(payload))


@router.get("/{entity_type}", response_model=ApiResponse[PaginatedData[dict[str, Any]]], summary="统一实体列表（分页）")
async def list_entities(
    entity_type: str,
    db: AsyncSession = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    q: str | None = Query(None, description="关键字，过滤 name/description"),
    style: str | None = Query(None, description="题材/风格（单值）"),
    visual_style: str | None = Query(None, description="画面表现形式（单值：真人/动漫）"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    service = StudioEntitiesService(db)
    payload, total = await service.list_entities(
        entity_type=entity_type,
        q=q,
        style=style,
        visual_style=visual_style,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
        workspace_id=ctx.workspace_id,
    )
    return paginated_response(payload, page=page, page_size=page_size, total=total)


@router.post("/{entity_type}", response_model=ApiResponse[dict[str, Any]], status_code=status.HTTP_201_CREATED, summary="统一创建实体")
async def create_entity(
    entity_type: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.create_entity(entity_type=entity_type, body=body)
    return created_response(payload)


@router.get("/{entity_type}/{entity_id}", response_model=ApiResponse[dict[str, Any]], summary="统一获取实体")
async def get_entity(entity_type: str, entity_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.get_entity(entity_type=entity_type, entity_id=entity_id)
    return success_response(payload)


@router.patch("/{entity_type}/{entity_id}", response_model=ApiResponse[dict[str, Any]], summary="统一更新实体")
async def update_entity(
    entity_type: str,
    entity_id: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.update_entity(entity_type=entity_type, entity_id=entity_id, body=body)
    return success_response(payload)


@router.delete("/{entity_type}/{entity_id}", response_model=ApiResponse[None], summary="统一删除实体")
async def delete_entity(entity_type: str, entity_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[None]:
    service = StudioEntitiesService(db)
    await service.delete_entity(entity_type=entity_type, entity_id=entity_id)
    return empty_response()


@router.get(
    "/{entity_type}/{entity_id}/images",
    response_model=ApiResponse[PaginatedData[dict[str, Any]]],
    summary="统一实体图片列表（分页）",
)
async def list_entity_images(
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    service = StudioEntitiesService(db)
    payload, total = await service.list_entity_images(
        entity_type=entity_type,
        entity_id=entity_id,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
    )
    return paginated_response(payload, page=page, page_size=page_size, total=total)


@router.post(
    "/{entity_type}/{entity_id}/images",
    response_model=ApiResponse[dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
    summary="统一创建实体图片",
)
async def create_entity_image(
    entity_type: str,
    entity_id: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.create_entity_image(entity_type=entity_type, entity_id=entity_id, body=body)
    return created_response(payload)


@router.patch(
    "/{entity_type}/{entity_id}/images/{image_id}",
    response_model=ApiResponse[dict[str, Any]],
    summary="统一更新实体图片",
)
async def update_entity_image(
    entity_type: str,
    entity_id: str,
    image_id: int,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.update_entity_image(
        entity_type=entity_type,
        entity_id=entity_id,
        image_id=image_id,
        body=body,
    )
    return success_response(payload)


@router.delete(
    "/{entity_type}/{entity_id}/images/{image_id}",
    response_model=ApiResponse[None],
    summary="统一删除实体图片",
)
async def delete_entity_image(
    entity_type: str,
    entity_id: str,
    image_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    service = StudioEntitiesService(db)
    await service.delete_entity_image(entity_type=entity_type, entity_id=entity_id, image_id=image_id)
    return empty_response()
