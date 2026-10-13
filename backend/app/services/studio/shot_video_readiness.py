"""镜头视频生成准备度聚合服务。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider
from app.models.studio import (
    Shot,
    ShotCandidateStatus,
    ShotDialogueCandidateStatus,
    ShotDetail,
    ShotExtractedCandidate,
    ShotExtractedDialogueCandidate,
    ShotFrameImage,
)
from app.models.task import GenerationTask, GenerationTaskStatus
from app.models.task_links import GenerationTaskLink
from app.schemas.studio.shots import ShotVideoReadinessCheck, ShotVideoReadinessRead
from app.services.common import entity_not_found
from app.services.studio.generation.video import (
    # 参考模式的帧要求必须与生成链路共用同一份定义：这里曾各自维护一份，
    # 新增 "reference" 时只改了 build_context，导致准备度把 reference 判为
    # 「未知参考模式」并让视频端点永远 409。
    REFERENCE_MODE,
    REQUIRED_FRAMES_BY_MODE,
    build_video_base_draft,
    build_video_context,
    derive_video_preview,
    resolve_reference_mode_file_ids,
)

_ACTIVE_TASK_STATUSES = (
    GenerationTaskStatus.pending,
    GenerationTaskStatus.running,
    GenerationTaskStatus.streaming,
)


def _check(key: str, ok: bool, message: str) -> ShotVideoReadinessCheck:
    return ShotVideoReadinessCheck(key=key, ok=ok, message=message)


async def _count_pending_candidates(db: AsyncSession, *, shot_id: str) -> tuple[int, int]:
    asset_stmt = (
        select(func.count(ShotExtractedCandidate.id))
        .where(ShotExtractedCandidate.shot_id == shot_id)
        .where(ShotExtractedCandidate.candidate_status == ShotCandidateStatus.pending)
    )
    dialogue_stmt = (
        select(func.count(ShotExtractedDialogueCandidate.id))
        .where(ShotExtractedDialogueCandidate.shot_id == shot_id)
        .where(ShotExtractedDialogueCandidate.candidate_status == ShotDialogueCandidateStatus.pending)
    )
    return int(await db.scalar(asset_stmt) or 0), int(await db.scalar(dialogue_stmt) or 0)


async def _has_active_video_task(db: AsyncSession, *, shot_id: str) -> bool:
    stmt = (
        select(func.count(GenerationTask.id))
        .select_from(GenerationTaskLink)
        .join(GenerationTask, GenerationTask.id == GenerationTaskLink.task_id)
        .where(GenerationTaskLink.resource_type == "video")
        .where(GenerationTaskLink.relation_type == "video")
        .where(GenerationTaskLink.relation_entity_id == shot_id)
        .where(GenerationTask.status.in_(_ACTIVE_TASK_STATUSES))
    )
    return bool(await db.scalar(stmt))


async def _reference_frames_ready(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
) -> ShotVideoReadinessCheck:
    required_frames = REQUIRED_FRAMES_BY_MODE.get(reference_mode)
    if required_frames is None:
        return _check("reference_frames_ready", False, f"未知参考模式：{reference_mode}")
    if not required_frames:
        return _check("reference_frames_ready", True, "当前参考模式不需要参考帧")

    stmt = select(ShotFrameImage).where(
        ShotFrameImage.shot_detail_id == shot_id,
        ShotFrameImage.frame_type.in_(required_frames),
    )
    rows = (await db.execute(stmt)).scalars().all()
    frame_map = {row.frame_type: row for row in rows}
    missing = [frame.value for frame in required_frames if not frame_map.get(frame) or not frame_map[frame].file_id]
    if missing:
        return _check("reference_frames_ready", False, f"缺少参考帧：{', '.join(missing)}")
    return _check("reference_frames_ready", True, "参考帧已就绪")


async def _reference_images_ready(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
) -> ShotVideoReadinessCheck:
    """参考图模式必须真的有参考图。

    参考图来自 IR 的有序参考列表，而角色卡只在「本镜头剧本内容里出现该角色」
    时才插入（见 `app/chains/prompts/ir.py::_collect_asset_references`）。所以纯
    空镜在参考图模式下会解析出 0 张图，提交时被 `validate_images_count` 判 400。
    那个报错发生在生成端点，用户在准备度面板上看到的却是「全部就绪」——这里把
    它提前暴露成一条可执行的检查项。
    """
    if reference_mode != REFERENCE_MODE:
        return _check("reference_images_ready", True, "当前参考模式不使用参考图")
    try:
        file_ids = await resolve_reference_mode_file_ids(db, shot_id=shot_id)
    except Exception as exc:  # noqa: BLE001 - 解析失败只应是「未就绪」，不该让准备度整体 500
        return _check("reference_images_ready", False, f"参考图解析失败：{exc}")
    if file_ids:
        return _check("reference_images_ready", True, f"已解析到 {len(file_ids)} 张参考图")
    return _check(
        "reference_images_ready",
        False,
        "参考图模式需要至少 1 张参考图，但本镜头没有可用参考图"
        "（角色卡只在剧本中出现该角色时才插入，空镜请改用「仅文本」模式）",
    )


async def _video_model_and_provider_ready(db: AsyncSession) -> tuple[ShotVideoReadinessCheck, ShotVideoReadinessCheck]:
    settings = await db.get(ModelSettings, 1)
    model_id = settings.default_video_model_id if settings else None
    if not model_id:
        return (
            _check("video_model_ready", False, "未配置默认视频模型"),
            _check("provider_ready", False, "未配置默认视频模型，无法检查供应商"),
        )
    model = await db.get(Model, model_id)
    if model is None:
        return (
            _check("video_model_ready", False, f"默认视频模型不存在：{model_id}"),
            _check("provider_ready", False, "默认视频模型不存在，无法检查供应商"),
        )
    if model.category != ModelCategoryKey.video:
        return (
            _check("video_model_ready", False, f"默认模型不是视频类别：{model_id}"),
            _check("provider_ready", False, "默认模型不是视频类别，无法检查供应商"),
        )
    provider = await db.get(Provider, model.provider_id)
    if provider is None:
        return (
            _check("video_model_ready", True, "默认视频模型可用"),
            _check("provider_ready", False, f"视频模型供应商不存在：{model.provider_id}"),
        )
    if not (provider.api_key or "").strip():
        return (
            _check("video_model_ready", True, "默认视频模型可用"),
            _check("provider_ready", False, f"视频模型供应商缺少 api_key：{provider.id}"),
        )
    return (
        _check("video_model_ready", True, "默认视频模型可用"),
        _check("provider_ready", True, "视频模型供应商可用"),
    )


async def get_shot_video_readiness(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
) -> ShotVideoReadinessRead:
    """实时聚合镜头视频生成准备度，不写入数据库状态。"""
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise ValueError(entity_not_found("Shot"))
    detail = await db.get(ShotDetail, shot_id)

    pending_assets, pending_dialogues = await _count_pending_candidates(db, shot_id=shot_id)
    extraction_ok = bool(shot.skip_extraction) or (
        shot.last_extracted_at is not None and pending_assets == 0 and pending_dialogues == 0
    )
    if extraction_ok:
        extraction_msg = "信息提取确认已完成" if not shot.skip_extraction else "当前镜头已标记为无需提取"
    else:
        extraction_msg = f"仍有待确认项：资产 {pending_assets} 项，对白 {pending_dialogues} 项"

    if detail is None:
        duration_check = _check("duration_ready", False, "缺少镜头详情，无法读取时长")
    else:
        duration = int(detail.duration or 0)
        duration_check = _check(
            "duration_ready",
            duration > 0,
            "镜头时长已配置" if duration > 0 else "请先配置镜头时长",
        )

    # 提示词检查刻意用 text_only + 空图做「维度隔离」：这里只回答「提示词能不能渲染出
    # 内容」，参考帧缺失由 _reference_frames_ready 单独报告。若传入真实 reference_mode，
    # build_video_context 会因缺帧抛 400，导致 prompt_ready 被误报为渲染失败。
    try:
        preview = await derive_video_preview(
            db,
            base=build_video_base_draft(shot_id=shot_id, prompt=None),
            context=await build_video_context(
                db,
                shot_id=shot_id,
                reference_mode="text_only",
                images=[],
            ),
        )
        prompt_ok = bool(preview.rendered_prompt.strip())
        prompt_message = "视频提示词可用" if prompt_ok else "视频提示词为空"
    except Exception as exc:  # noqa: BLE001
        prompt_ok = False
        prompt_message = f"视频提示词渲染失败：{exc}"

    active_video_task = await _has_active_video_task(db, shot_id=shot_id)
    model_check, provider_check = await _video_model_and_provider_ready(db)
    checks = [
        _check("extraction_ready", extraction_ok, extraction_msg),
        duration_check,
        _check("prompt_ready", prompt_ok, prompt_message),
        await _reference_frames_ready(db, shot_id=shot_id, reference_mode=reference_mode),
        await _reference_images_ready(db, shot_id=shot_id, reference_mode=reference_mode),
        model_check,
        provider_check,
        _check(
            "no_active_video_task",
            not active_video_task,
            "当前没有进行中的视频任务" if not active_video_task else "当前已有视频生成任务进行中",
        ),
    ]
    return ShotVideoReadinessRead(
        shot_id=shot_id,
        reference_mode=reference_mode,
        ready=all(item.ok for item in checks),
        checks=checks,
    )
