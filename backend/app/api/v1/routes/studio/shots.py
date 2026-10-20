"""Shot 相关 CRUD：Shot / ShotDetail / ShotDialogLine / 资源 Link。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.scoping import (
    get_dialog_line_in_workspace,
    get_frame_image_in_workspace,
    get_shot_detail_in_workspace,
    get_shot_in_workspace,
    get_shot_link_in_workspace,
    require_scoped_resource,
)
from app.dependencies import WorkspaceContext, get_db, get_workspace_context
from app.services.studio.shot_assets import (
    create_project_asset_link as create_project_asset_link_service,
    delete_project_asset_link as delete_project_asset_link_service,
    list_project_asset_links_paginated,
    list_shot_linked_assets_paginated,
)
from app.services.studio.shot_details import (
    create as create_shot_detail_service,
    get as get_shot_detail_service,
    list_paginated as list_shot_details_paginated,
    update as update_shot_detail_service,
    delete as delete_shot_detail_service,
)
from app.services.studio.shot_dialogs import (
    create as create_shot_dialog_line_service,
    list_paginated as list_shot_dialog_lines_paginated,
    update as update_shot_dialog_line_service,
    delete as delete_shot_dialog_line_service,
)
from app.services.studio.shot_frames import (
    create as create_shot_frame_image_service,
    delete as delete_shot_frame_image_service,
    list_paginated as list_shot_frame_images_paginated,
    update as update_shot_frame_image_service,
)
from app.services.studio.shots import (
    build_shot_read,
    create as create_shot_service,
    delete as delete_shot_service,
    get as get_shot_service,
    list_paginated as list_shots_paginated,
    update as update_shot_service,
)
from app.services.studio import (
    accept_shot_extracted_dialogue_candidate,
    build_shot_preparation_state,
    get_shot_assets_overview,
    ignore_shot_extracted_candidate,
    ignore_shot_extracted_dialogue_candidate,
    link_existing_asset_for_preparation,
    link_shot_extracted_candidate,
    list_shot_extracted_candidates,
    list_shot_extracted_dialogue_candidates,
    get_shot_video_readiness,
    adopt_shot_video_version,
    list_shot_video_versions,
    list_shot_runtime_summary_by_chapter,
    set_skip_extraction,
)
from app.services.studio.generation.video import (
    build_video_base_draft,
    build_video_context,
    derive_video_preview,
)
from app.services.studio.generation.video.derive_preview import to_shot_video_prompt_preview_read
from app.schemas.common import ApiResponse, PaginatedData, created_response, empty_response, success_response
from app.schemas.skills.script_processing import StudioScriptExtractionDraft
from app.services.studio.shot_extraction_draft import build_script_extraction_draft_for_shot
from app.services.studio.batch_candidate_assets import create_assets_from_extraction_candidates
from app.schemas.studio.shots import (
    ProjectActorLinkRead,
    ProjectAssetLinkCreate,
    ProjectCostumeLinkRead,
    ShotAssetsOverviewRead,
    ShotLinkedAssetItem,
    ShotCreate,
    ShotDetailCreate,
    ShotDetailRead,
    ShotDetailUpdate,
    ShotDialogLineCreate,
    ShotDialogLineRead,
    ShotDialogLineUpdate,
    ProjectPropLinkRead,
    ShotRead,
    ShotRuntimeSummaryRead,
    ProjectSceneLinkRead,
    ShotUpdate,
    ShotFrameImageCreate,
    ShotFrameImageRead,
    ShotFrameImageUpdate,
    ShotExtractedCandidateLinkRequest,
    ShotExtractedCandidateRead,
    BatchCreateAssetsFromCandidatesRequest,
    ShotExtractedDialogueCandidateAcceptRequest,
    ShotExtractedDialogueCandidateRead,
    ShotPreparationMutationAction,
    ShotPreparationLinkRequest,
    ShotPreparationMutationResultRead,
    ShotPreparationStateRead,
    ShotSkipExtractionUpdate,
    ShotVideoReadinessRead,
    ShotVideoVersionAdoptRequest,
    ShotVideoVersionRead,
    ShotVideoPromptPreviewRead,
)

router = APIRouter(
    # router 级守卫：任何带 `shot_id` 路径参数的端点自动校验工作区归属，
    # 写方法额外要求 editor。新增端点无需重复声明即默认受保护。
    dependencies=[Depends(require_scoped_resource("shot_id", get_shot_in_workspace))],
)
details_router = APIRouter(
    # shot_details 与 shots 共享主键，但「不存在」的文案要保持 ShotDetail not found。
    dependencies=[Depends(require_scoped_resource("shot_id", get_shot_detail_in_workspace))],
)
dialog_router = APIRouter(
    dependencies=[Depends(require_scoped_resource("line_id", get_dialog_line_in_workspace))],
)
links_router = APIRouter(
    dependencies=[Depends(require_scoped_resource("link_id", get_shot_link_in_workspace))],
)
frames_router = APIRouter(
    dependencies=[Depends(require_scoped_resource("image_id", get_frame_image_in_workspace))],
)

SHOT_ORDER_FIELDS = {"index", "title", "status", "created_at", "updated_at"}
DETAIL_ORDER_FIELDS = {"id"}
DIALOG_ORDER_FIELDS = {"index", "id", "created_at", "updated_at"}
LINK_ORDER_FIELDS = {"id", "created_at", "updated_at"}
FRAME_IMAGE_ORDER_FIELDS = {"id", "frame_type", "created_at", "updated_at"}


# ---------- Shot ----------


@router.get(
    "",
    response_model=ApiResponse[PaginatedData[ShotRead]],
    summary="镜头列表（分页）",
)
async def list_shots(
    db: AsyncSession = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    chapter_id: str | None = Query(None, description="按章节过滤"),
    q: str | None = Query(None, description="关键字，过滤 title/script_excerpt"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[ShotRead]]:
    return await list_shots_paginated(
        db,
        chapter_id=chapter_id,
        q=q,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
        allow_fields=SHOT_ORDER_FIELDS,
        workspace_id=ctx.workspace_id,
    )


@router.post(
    "",
    response_model=ApiResponse[ShotRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建镜头",
)
async def create_shot(
    body: ShotCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotRead]:
    obj = await create_shot_service(db, body=body)
    return created_response(await build_shot_read(db, shot=obj))


@router.get(
    "/runtime-summary",
    response_model=ApiResponse[list[ShotRuntimeSummaryRead]],
    summary="按章节获取镜头运行时任务态摘要",
)
async def list_shot_runtime_summary(
    chapter_id: str = Query(..., description="章节 ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ShotRuntimeSummaryRead]]:
    rows = await list_shot_runtime_summary_by_chapter(db, chapter_id=chapter_id)
    return success_response(rows)


@router.get(
    "/{shot_id}/extraction-draft",
    response_model=ApiResponse[StudioScriptExtractionDraft],
    summary="分镜详情：按镜头关联拼装 StudioScriptExtractionDraft",
)
async def get_shot_extraction_draft(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StudioScriptExtractionDraft]:
    data = await build_script_extraction_draft_for_shot(db, shot_id)
    return success_response(data)


@router.get(
    "/{shot_id}/extracted-candidates",
    response_model=ApiResponse[list[ShotExtractedCandidateRead]],
    summary="获取镜头提取候选项",
)
async def get_shot_extracted_candidates(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ShotExtractedCandidateRead]]:
    rows = await list_shot_extracted_candidates(db, shot_id=shot_id)
    return success_response([ShotExtractedCandidateRead.model_validate(row) for row in rows])


@router.get(
    "/{shot_id}/extracted-dialogue-candidates",
    response_model=ApiResponse[list[ShotExtractedDialogueCandidateRead]],
    summary="获取镜头提取对白候选项",
)
async def get_shot_extracted_dialogue_candidates(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ShotExtractedDialogueCandidateRead]]:
    rows = await list_shot_extracted_dialogue_candidates(db, shot_id=shot_id)
    return success_response([ShotExtractedDialogueCandidateRead.model_validate(row) for row in rows])


@router.get(
    "/{shot_id}/assets-overview",
    response_model=ApiResponse[ShotAssetsOverviewRead],
    summary="获取镜头资产总览（已关联资产 + 提取候选）",
)
async def get_shot_assets_overview_api(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotAssetsOverviewRead]:
    data = await get_shot_assets_overview(db, shot_id=shot_id)
    return success_response(data)


@router.get(
    "/{shot_id}/preparation-state",
    response_model=ApiResponse[ShotPreparationStateRead],
    summary="获取镜头准备页聚合状态",
)
async def get_shot_preparation_state_api(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotPreparationStateRead]:
    data = await build_shot_preparation_state(db, shot_id=shot_id)
    return success_response(data)


@router.post(
    "/{shot_id}/preparation-link",
    response_model=ApiResponse[ShotPreparationMutationResultRead],
    summary="准备页关联现有实体并返回最新聚合状态",
)
async def link_existing_asset_for_preparation_api(
    shot_id: str,
    body: ShotPreparationLinkRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotPreparationMutationResultRead]:
    data = await link_existing_asset_for_preparation(
        db,
        project_id=body.project_id,
        chapter_id=body.chapter_id,
        shot_id=shot_id,
        entity_type=body.entity_type,
        linked_entity_id=body.linked_entity_id,
    )
    return success_response(
        ShotPreparationMutationResultRead(
            action=ShotPreparationMutationAction.link_asset_candidate,
            state=data,
        )
    )


@router.get(
    "/{shot_id}/video-prompt-preview",
    response_model=ApiResponse[ShotVideoPromptPreviewRead],
    summary="预览镜头视频提示词",
)
async def preview_shot_video_prompt(
    shot_id: str,
    template_id: str | None = Query(None, description="指定视频提示词模板 ID；不传则使用默认模板"),
    reference_mode: str = Query(
        "text_only",
        description=(
            "参考模式：first/last/key/first_last/first_last_key/text_only。"
            "默认 text_only 只渲染提示词本身；传真实模式时会连同该模式要求的参考帧一起渲染"
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotVideoPromptPreviewRead]:
    derived = await derive_video_preview(
        db,
        base=build_video_base_draft(shot_id=shot_id, prompt=None),
        context=await build_video_context(
            db,
            shot_id=shot_id,
            reference_mode=reference_mode,
            images=[],
            template_id=template_id,
        ),
    )
    return success_response(to_shot_video_prompt_preview_read(derived=derived))


@router.get(
    "/{shot_id}/video-readiness",
    response_model=ApiResponse[ShotVideoReadinessRead],
    summary="获取镜头视频生成准备度",
)
async def get_shot_video_readiness_api(
    shot_id: str,
    reference_mode: str = Query("text_only", description="参考模式：first/last/key/first_last/first_last_key/text_only"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotVideoReadinessRead]:
    data = await get_shot_video_readiness(db, shot_id=shot_id, reference_mode=reference_mode)
    return success_response(data)


@router.get(
    "/{shot_id}/video-versions",
    response_model=ApiResponse[list[ShotVideoVersionRead]],
    summary="获取镜头视频版本（抽卡历史）",
)
async def list_shot_video_versions_api(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ShotVideoVersionRead]]:
    """按创建时间倒序返回该镜头的全部视频版本，历史版本一律保留。"""
    data = await list_shot_video_versions(db, shot_id=shot_id)
    return success_response(data)


@router.post(
    "/{shot_id}/video-versions/adopt",
    response_model=ApiResponse[ShotRead],
    summary="切换镜头当前采用的视频版本",
)
async def adopt_shot_video_version_api(
    shot_id: str,
    body: ShotVideoVersionAdoptRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotRead]:
    """把镜头当前采用的视频切到指定历史版本；不删除任何旧版本文件。"""
    shot = await adopt_shot_video_version(db, shot_id=shot_id, file_id=body.file_id)
    await db.commit()
    data = await build_shot_read(db, shot=shot)
    return success_response(data)


@router.patch(
    "/{shot_id}/skip-extraction",
    response_model=ApiResponse[ShotPreparationMutationResultRead],
    summary="设置是否跳过镜头信息提取",
)
async def update_shot_skip_extraction(
    shot_id: str,
    body: ShotSkipExtractionUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotPreparationMutationResultRead]:
    shot = await set_skip_extraction(db, shot_id=shot_id, skip=body.skip)
    data = await build_shot_preparation_state(db, shot_id=shot.id)
    return success_response(
        ShotPreparationMutationResultRead(
            action=(
                ShotPreparationMutationAction.skip_extraction
                if body.skip
                else ShotPreparationMutationAction.resume_extraction
            ),
            state=data,
        )
    )


@router.patch(
    "/extracted-candidates/{candidate_id}/link",
    response_model=ApiResponse[ShotPreparationMutationResultRead],
    summary="确认并关联镜头提取候选项",
)
async def link_extracted_candidate(
    candidate_id: int,
    body: ShotExtractedCandidateLinkRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotPreparationMutationResultRead]:
    row = await link_shot_extracted_candidate(
        db,
        candidate_id=candidate_id,
        linked_entity_id=body.linked_entity_id,
    )
    data = await build_shot_preparation_state(db, shot_id=row.shot_id)
    return success_response(
        ShotPreparationMutationResultRead(
            action=ShotPreparationMutationAction.link_asset_candidate,
            state=data,
        )
    )


@router.patch(
    "/extracted-candidates/{candidate_id}/ignore",
    response_model=ApiResponse[ShotPreparationMutationResultRead],
    summary="忽略镜头提取候选项",
)
async def ignore_extracted_candidate(
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotPreparationMutationResultRead]:
    row = await ignore_shot_extracted_candidate(db, candidate_id=candidate_id)
    data = await build_shot_preparation_state(db, shot_id=row.shot_id)
    return success_response(
        ShotPreparationMutationResultRead(
            action=ShotPreparationMutationAction.ignore_asset_candidate,
            state=data,
        )
    )


@router.post(
    "/extracted-candidates/batch-create-assets",
    response_model=ApiResponse[dict[str, Any]],
    summary="一键从提取候选项创建/关联资产（人物/场景/道具/服装）",
)
async def batch_create_assets_from_candidates(
    body: BatchCreateAssetsFromCandidatesRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    """按章节遍历 pending 提取候选，批量创建资产实体并关联到分镜。

    ToonFlow 式「一键提取资产」：提取完成后一次性把人物/场景/道具/服装落库。
    """
    result = await create_assets_from_extraction_candidates(
        db,
        chapter_id=body.chapter_id,
        types=body.types,
    )
    return success_response(result)


@router.patch(
    "/extracted-dialogue-candidates/{candidate_id}/accept",
    response_model=ApiResponse[ShotPreparationMutationResultRead],
    summary="接受镜头提取对白候选项",
)
async def accept_extracted_dialogue_candidate(
    candidate_id: int,
    body: ShotExtractedDialogueCandidateAcceptRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotPreparationMutationResultRead]:
    row = await accept_shot_extracted_dialogue_candidate(db, candidate_id=candidate_id, body=body)
    data = await build_shot_preparation_state(db, shot_id=row.shot_id)
    return success_response(
        ShotPreparationMutationResultRead(
            action=ShotPreparationMutationAction.accept_dialogue_candidate,
            state=data,
        )
    )


@router.patch(
    "/extracted-dialogue-candidates/{candidate_id}/ignore",
    response_model=ApiResponse[ShotPreparationMutationResultRead],
    summary="忽略镜头提取对白候选项",
)
async def ignore_extracted_dialogue_candidate(
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotPreparationMutationResultRead]:
    row = await ignore_shot_extracted_dialogue_candidate(db, candidate_id=candidate_id)
    data = await build_shot_preparation_state(db, shot_id=row.shot_id)
    return success_response(
        ShotPreparationMutationResultRead(
            action=ShotPreparationMutationAction.ignore_dialogue_candidate,
            state=data,
        )
    )


@router.get(
    "/{shot_id}",
    response_model=ApiResponse[ShotRead],
    summary="获取镜头",
)
async def get_shot(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotRead]:
    obj = await get_shot_service(db, shot_id=shot_id)
    return success_response(await build_shot_read(db, shot=obj))


@router.patch(
    "/{shot_id}",
    response_model=ApiResponse[ShotRead],
    summary="更新镜头",
)
async def update_shot(
    shot_id: str,
    body: ShotUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotRead]:
    obj = await update_shot_service(db, shot_id=shot_id, body=body)
    return success_response(await build_shot_read(db, shot=obj))


@router.delete(
    "/{shot_id}",
    response_model=ApiResponse[None],
    summary="删除镜头",
)
async def delete_shot(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_shot_service(db, shot_id=shot_id)
    return empty_response()


@router.get(
    "/{shot_id}/linked-assets",
    response_model=ApiResponse[PaginatedData[ShotLinkedAssetItem]],
    summary="获取镜头关联的角色/道具/场景/服装（分页）",
)
async def list_shot_linked_assets(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[ShotLinkedAssetItem]]:
    return await list_shot_linked_assets_paginated(
        db,
        shot_id=shot_id,
        page=page,
        page_size=page_size,
    )


# ---------- ShotDetail ----------


@details_router.get(
    "",
    response_model=ApiResponse[PaginatedData[ShotDetailRead]],
    summary="镜头细节列表（分页）",
)
async def list_shot_details(
    db: AsyncSession = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    shot_id: str | None = Query(None, description="按镜头过滤（id 同 shot_id）"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[ShotDetailRead]]:
    return await list_shot_details_paginated(
        db,
        shot_id=shot_id,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
        allow_fields=DETAIL_ORDER_FIELDS,
        workspace_id=ctx.workspace_id,
    )


@details_router.post(
    "",
    response_model=ApiResponse[ShotDetailRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建镜头细节",
)
async def create_shot_detail(
    body: ShotDetailCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotDetailRead]:
    obj = await create_shot_detail_service(db, body=body)
    return created_response(ShotDetailRead.model_validate(obj))


@details_router.get(
    "/{shot_id}",
    response_model=ApiResponse[ShotDetailRead],
    summary="获取镜头细节",
)
async def get_shot_detail(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotDetailRead]:
    obj = await get_shot_detail_service(db, shot_id=shot_id)
    return success_response(ShotDetailRead.model_validate(obj))


@details_router.patch(
    "/{shot_id}",
    response_model=ApiResponse[ShotDetailRead],
    summary="更新镜头细节",
)
async def update_shot_detail(
    shot_id: str,
    body: ShotDetailUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotDetailRead]:
    obj = await update_shot_detail_service(db, shot_id=shot_id, body=body)
    return success_response(ShotDetailRead.model_validate(obj))


@details_router.delete(
    "/{shot_id}",
    response_model=ApiResponse[None],
    summary="删除镜头细节",
)
async def delete_shot_detail(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_shot_detail_service(db, shot_id=shot_id)
    return empty_response()


# ---------- ShotDialogLine ----------


@dialog_router.get(
    "",
    response_model=ApiResponse[PaginatedData[ShotDialogLineRead]],
    summary="镜头对话行列表（分页）",
)
async def list_shot_dialog_lines(
    db: AsyncSession = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    shot_detail_id: str | None = Query(None, description="按镜头细节过滤"),
    q: str | None = Query(None, description="关键字，过滤 text"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[ShotDialogLineRead]]:
    return await list_shot_dialog_lines_paginated(
        db,
        shot_detail_id=shot_detail_id,
        q=q,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
        allow_fields=DIALOG_ORDER_FIELDS,
        workspace_id=ctx.workspace_id,
    )


@dialog_router.post(
    "",
    response_model=ApiResponse[ShotDialogLineRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建镜头对话行",
)
async def create_shot_dialog_line(
    body: ShotDialogLineCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotDialogLineRead]:
    obj = await create_shot_dialog_line_service(db, body=body)
    return created_response(ShotDialogLineRead.model_validate(obj))


@dialog_router.patch(
    "/{line_id}",
    response_model=ApiResponse[ShotDialogLineRead],
    summary="更新镜头对话行",
)
async def update_shot_dialog_line(
    line_id: int,
    body: ShotDialogLineUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotDialogLineRead]:
    obj = await update_shot_dialog_line_service(db, line_id=line_id, body=body)
    return success_response(ShotDialogLineRead.model_validate(obj))


@dialog_router.delete(
    "/{line_id}",
    response_model=ApiResponse[None],
    summary="删除镜头对话行",
)
async def delete_shot_dialog_line(
    line_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_shot_dialog_line_service(db, line_id=line_id)
    return empty_response()


# ---------- ShotFrameImage ----------


@frames_router.get(
    "",
    response_model=ApiResponse[PaginatedData[ShotFrameImageRead]],
    summary="镜头分镜帧图片列表（分页）",
)
async def list_shot_frame_images(
    db: AsyncSession = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    shot_detail_id: str | None = Query(None, description="按镜头细节过滤"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[ShotFrameImageRead]]:
    return await list_shot_frame_images_paginated(
        db,
        shot_detail_id=shot_detail_id,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
        allow_fields=FRAME_IMAGE_ORDER_FIELDS,
        workspace_id=ctx.workspace_id,
    )


@frames_router.post(
    "",
    response_model=ApiResponse[ShotFrameImageRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建镜头分镜帧图片",
)
async def create_shot_frame_image(
    body: ShotFrameImageCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotFrameImageRead]:
    obj = await create_shot_frame_image_service(db, body=body)
    return created_response(ShotFrameImageRead.model_validate(obj))


@frames_router.patch(
    "/{image_id}",
    response_model=ApiResponse[ShotFrameImageRead],
    summary="更新镜头分镜帧图片",
)
async def update_shot_frame_image(
    image_id: int,
    body: ShotFrameImageUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotFrameImageRead]:
    obj = await update_shot_frame_image_service(db, image_id=image_id, body=body)
    return success_response(ShotFrameImageRead.model_validate(obj))


@frames_router.delete(
    "/{image_id}",
    response_model=ApiResponse[None],
    summary="删除镜头分镜帧图片",
)
async def delete_shot_frame_image(
    image_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_shot_frame_image_service(db, image_id=image_id)
    return empty_response()


# ---------- Links（镜头引用资产） ----------


@links_router.get(
    "/{entity_type}",
    response_model=ApiResponse[PaginatedData[Any]],
    summary="项目-章节-镜头-实体关联列表（分页）",
)
async def list_project_entity_links(
    entity_type: str,
    db: AsyncSession = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    project_id: str | None = Query(None),
    chapter_id: str | None = Query(None),
    shot_id: str | None = Query(None),
    asset_id: str | None = Query(None),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[Any]]:
    return await list_project_asset_links_paginated(
        db=db,
        entity_type=entity_type,
        project_id=project_id,
        chapter_id=chapter_id,
        shot_id=shot_id,
        asset_id=asset_id,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
        allow_fields=LINK_ORDER_FIELDS,
        workspace_id=ctx.workspace_id,
    )


@links_router.post(
    "/actor",
    response_model=ApiResponse[ProjectActorLinkRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建项目-章节-镜头-演员关联",
)
async def create_project_actor_link(
    body: ProjectAssetLinkCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProjectActorLinkRead]:
    obj = await create_project_asset_link_service(db, entity_type="actor", body=body)
    return created_response(ProjectActorLinkRead.model_validate(obj))



@links_router.delete(
    "/actor/{link_id}",
    response_model=ApiResponse[None],
    summary="删除项目-章节-镜头-演员关联",
)
async def delete_project_actor_link(
    link_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_project_asset_link_service(db, entity_type="actor", link_id=link_id)
    return empty_response()


@links_router.post(
    "/scene",
    response_model=ApiResponse[ProjectSceneLinkRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建项目-章节-镜头-场景关联",
)
async def create_project_scene_link(
    body: ProjectAssetLinkCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProjectSceneLinkRead]:
    obj = await create_project_asset_link_service(db, entity_type="scene", body=body)
    return created_response(ProjectSceneLinkRead.model_validate(obj))



@links_router.delete(
    "/scene/{link_id}",
    response_model=ApiResponse[None],
    summary="删除项目-章节-镜头-场景关联",
)
async def delete_project_scene_link(
    link_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_project_asset_link_service(db, entity_type="scene", link_id=link_id)
    return empty_response()


@links_router.post(
    "/prop",
    response_model=ApiResponse[ProjectPropLinkRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建项目-章节-镜头-道具关联",
)
async def create_project_prop_link(
    body: ProjectAssetLinkCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProjectPropLinkRead]:
    obj = await create_project_asset_link_service(db, entity_type="prop", body=body)
    return created_response(ProjectPropLinkRead.model_validate(obj))



@links_router.delete(
    "/prop/{link_id}",
    response_model=ApiResponse[None],
    summary="删除项目-章节-镜头-道具关联",
)
async def delete_project_prop_link(
    link_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_project_asset_link_service(db, entity_type="prop", link_id=link_id)
    return empty_response()


@links_router.post(
    "/costume",
    response_model=ApiResponse[ProjectCostumeLinkRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建项目-章节-镜头-服装关联",
)
async def create_project_costume_link(
    body: ProjectAssetLinkCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProjectCostumeLinkRead]:
    obj = await create_project_asset_link_service(db, entity_type="costume", body=body)
    return created_response(ProjectCostumeLinkRead.model_validate(obj))


@links_router.delete(
    "/costume/{link_id}",
    response_model=ApiResponse[None],
    summary="删除项目-章节-镜头-服装关联",
)
async def delete_project_costume_link(
    link_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_project_asset_link_service(db, entity_type="costume", link_id=link_id)
    return empty_response()
