from __future__ import annotations

import base64
import mimetypes
from typing import get_args

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput, VideoGenerationResult, VideoRatio
from app.core.tasks import VideoGenerationTask
from app.models.llm import Model, ModelCategoryKey, ModelSettings
from app.models.task_links import GenerationTaskLink
from app.models.studio import Chapter, FileItem, Project, Shot, ShotDetail, ShotFrameType
from app.models.types import FileUsageKind
from app.services.common import entity_not_found
from app.services.llm.provider_resolver import resolve_provider_config_by_model
from app.services.studio.file_usages import sync_usage_from_shot_context
from app.services.studio.generation.video import (
    REFERENCE_MODE,
    REQUIRED_FRAMES_BY_MODE,
    build_video_base_draft,
    build_video_context,
    build_video_submission_payload,
    resolve_reference_mode_file_ids,
    validate_images_count,
)
from app.services.studio.shot_status import recompute_shot_status
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_logging import log_task_event, log_task_failure
from app.utils.files import create_file_from_url_or_b64

async def validate_shot_and_duration(db: AsyncSession, shot_id: str) -> ShotDetail:
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail=entity_not_found("Shot"))
    shot_detail = await db.get(ShotDetail, shot_id)
    if shot_detail is None:
        raise HTTPException(status_code=404, detail=entity_not_found("ShotDetail"))
    if shot_detail.duration is None or shot_detail.duration <= 0:
        raise HTTPException(status_code=400, detail="Shot duration is not configured; please set shot duration first")
    return shot_detail


async def file_id_to_data_url(db: AsyncSession, *, file_id: str) -> str:
    file_obj = await db.get(FileItem, file_id)
    if file_obj is None or not file_obj.storage_key:
        raise HTTPException(status_code=400, detail=f"Invalid image file_id: {file_id}")
    try:
        content = await storage.download_file(key=file_obj.storage_key)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid image file_id: {file_id}") from None
    if not content:
        raise HTTPException(status_code=400, detail=f"Invalid image file_id: {file_id}")

    content_type: str | None = None
    try:
        info = await storage.get_file_info(key=file_obj.storage_key)
        content_type = (info.content_type or "").strip().lower() or None
    except Exception:  # noqa: BLE001
        content_type = None
    if not content_type:
        guessed_type, _ = mimetypes.guess_type(file_obj.storage_key)
        content_type = (guessed_type or "").strip().lower() or None
    if not content_type or not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"Invalid image file_id: {file_id}")

    image_format = content_type.split("/", 1)[1].split(";", 1)[0].strip().lower() or "png"
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:image/{image_format};base64,{encoded}"


async def preview_prompt_and_images(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
    prompt: str | None,
    images: list[str] | None = None,
) -> tuple[str, list[str], dict | None]:
    shot_detail = await validate_shot_and_duration(db, shot_id)
    base = build_video_base_draft(shot_id=shot_id, prompt=prompt)
    context = await build_video_context(
        db,
        shot_id=shot_id,
        reference_mode=reference_mode,
        images=images,
    )
    submission = await build_video_submission_payload(db, base=base, context=context)
    if not submission.prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    prompt_preview_payload = submission.extra.get("prompt_preview")
    if isinstance(prompt_preview_payload, dict):
        pack = prompt_preview_payload.get("pack")
        return submission.prompt, submission.images, pack if isinstance(pack, dict) else None
    return submission.prompt, submission.images, None


async def resolve_default_video_model(db: AsyncSession) -> Model:
    settings_row = await db.get(ModelSettings, 1)
    model_id = settings_row.default_video_model_id if settings_row else None
    if not model_id:
        raise HTTPException(
            status_code=503,
            detail="No default video model configured; please set ModelSettings.default_video_model_id first",
        )
    model = await db.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=503, detail=f"Configured default video model not found: {model_id}")
    if model.category != ModelCategoryKey.video:
        raise HTTPException(
            status_code=503,
            detail=f"Configured default video model is not video category: {model_id} (category={model.category})",
        )
    return model


async def load_provider_config_by_model(db: AsyncSession, model: Model) -> ProviderConfig:
    resolved = await resolve_provider_config_by_model(db, model=model)
    return ProviderConfig(
        provider=resolved.provider_key,  # type: ignore[arg-type]
        api_key=resolved.api_key,
        base_url=resolved.base_url,
    )


def _normalize_optional_text(value: str | None) -> str | None:
    """归一化可选文本参数：空字符串视为未设置。"""
    normalized = (value or "").strip()
    return normalized or None


_VALID_VIDEO_RATIOS = set(get_args(VideoRatio))


def _validate_video_ratio(value: str, *, source: str) -> str:
    """校验比例取值合法，避免脏数据在提交阶段才炸成 500。"""
    if value not in _VALID_VIDEO_RATIOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid video ratio {value!r} from {source}; "
                f"allowed: {sorted(_VALID_VIDEO_RATIOS)}"
            ),
        )
    return value


async def resolve_effective_video_options(
    db: AsyncSession,
    *,
    shot_id: str,
    shot_detail: ShotDetail,
    requested_ratio: str | None,
) -> str:
    """解析视频比例：请求参数 → 分镜覆盖 → 项目默认。

    评审 R-15：`shot_details.override_video_ratio` 与 `projects.default_video_ratio`
    两列建了却从未被后端读取（继承逻辑只写在前端），导致同一个分镜走前端能生成、
    直连 API 却必然 400。这里把继承链补回后端，作为唯一权威。
    """
    req_ratio = _normalize_optional_text(requested_ratio)
    if req_ratio:
        return _validate_video_ratio(req_ratio, source="request")

    override_ratio = _normalize_optional_text(shot_detail.override_video_ratio)
    if override_ratio:
        return _validate_video_ratio(
            override_ratio,
            source=f"shot_details.override_video_ratio (shot_id={shot_id})",
        )

    project_ratio: str | None = None
    shot = await db.get(Shot, shot_id)
    if shot is not None and shot.chapter_id:
        chapter = await db.get(Chapter, shot.chapter_id)
        if chapter is not None and chapter.project_id:
            project = await db.get(Project, chapter.project_id)
            if project is not None:
                project_ratio = _normalize_optional_text(project.default_video_ratio)
    if project_ratio:
        return _validate_video_ratio(project_ratio, source="projects.default_video_ratio")

    raise HTTPException(
        status_code=400,
        detail=(
            "ratio is required: 请求未指定 ratio，该分镜未设置 override_video_ratio，"
            "所属项目也未设置 default_video_ratio"
        ),
    )


async def build_run_args(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
    prompt: str | None,
    images: list[str],
    ratio: str | None,
    use_context_ir: bool = False,
    skill_id: str | None = None,
) -> dict:
    model = await resolve_default_video_model(db)
    provider_cfg = await load_provider_config_by_model(db, model)
    shot_detail = await validate_shot_and_duration(db, shot_id)
    resolved_ratio = await resolve_effective_video_options(
        db,
        shot_id=shot_id,
        shot_detail=shot_detail,
        requested_ratio=ratio,
    )
    base = build_video_base_draft(shot_id=shot_id, prompt=prompt)

    # 参考图模式：客户端不传 images 时由服务端按 IR 的有序参考列表补全，
    # 保证上传的第 N 张图与提示词里的 <Picture N> 一一对应。
    if reference_mode == REFERENCE_MODE and not [
        item for item in (images or []) if str(item).strip()
    ]:
        images = await resolve_reference_mode_file_ids(
            db,
            shot_id=shot_id,
            ratio=resolved_ratio,
        )

    context = await build_video_context(
        db,
        shot_id=shot_id,
        reference_mode=reference_mode,
        images=images,
        provider=provider_cfg.provider,
        model=model.name,
        ratio=resolved_ratio,
    )
    submission = await build_video_submission_payload(db, base=base, context=context)
    validate_images_count(reference_mode, submission.images)

    final_prompt = submission.prompt.strip()
    if not final_prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    if reference_mode == REFERENCE_MODE:
        # 参考图模式：上传顺序即 IR 参考列表顺序，与提示词里的 <Picture N> 一一对应。
        input_payload: dict = {
            "prompt": final_prompt,
            "reference_images": [
                await file_id_to_data_url(db, file_id=file_id)
                for file_id in submission.images
            ],
            "model": model.name,
            "ratio": resolved_ratio,
            "seconds": shot_detail.duration,
        }
    else:
        required_frames = tuple(
            ShotFrameType(item) for item in REQUIRED_FRAMES_BY_MODE[reference_mode]
        )
        frame_data_urls = [
            await file_id_to_data_url(db, file_id=file_id) for file_id in submission.images
        ]
        frame_map = {ft: frame_data_urls[i] for i, ft in enumerate(required_frames)}
        input_payload = {
            "prompt": final_prompt,
            "first_frame_base64": frame_map.get(ShotFrameType.first),
            "last_frame_base64": frame_map.get(ShotFrameType.last),
            "key_frame_base64": frame_map.get(ShotFrameType.key),
            "model": model.name,
            "ratio": resolved_ratio,
            "seconds": shot_detail.duration,
        }

    # A5：平台自带的提示词优化，默认关闭（提示词内容由 Jellyfish 自己控制）。
    if use_context_ir:
        input_payload["use_context_ir"] = True
        if skill_id:
            input_payload["skill_id"] = skill_id

    run_args = {
        "shot_id": shot_id,
        "provider": provider_cfg.provider,
        "api_key": provider_cfg.api_key,
        "base_url": provider_cfg.base_url,
        "input": input_payload,
    }
    prompt_preview_payload = submission.extra.get("prompt_preview")
    if isinstance(prompt_preview_payload, dict):
        run_args["prompt_preview"] = prompt_preview_payload
    return run_args


async def persist_generated_video_to_shot(
    session: AsyncSession,
    *,
    task_id: str,
    shot_id: str,
    result: VideoGenerationResult,
    provider: str,
    api_key: str,
) -> FileItem:
    url = (result.url or "").strip()
    if not url:
        raise RuntimeError("Video generation result has no download url")

    url_headers: dict[str, str] | None = None
    if provider == "openai":
        url_headers = {"Authorization": f"Bearer {api_key}"}

    file_obj = await create_file_from_url_or_b64(
        session,
        url=url,
        name=f"shot-{shot_id}-video",
        prefix=f"generated-videos/shots/{shot_id}",
        url_request_headers=url_headers,
        httpx_timeout=600.0,
    )

    link_stmt = (
        select(GenerationTaskLink)
        .where(
            GenerationTaskLink.task_id == task_id,
            GenerationTaskLink.resource_type == "video",
            GenerationTaskLink.relation_type == "video",
            GenerationTaskLink.relation_entity_id == shot_id,
        )
        .limit(1)
    )
    link_row = (await session.execute(link_stmt)).scalars().first()
    if link_row is not None:
        link_row.file_id = file_obj.id

    shot = await session.get(Shot, shot_id)
    if shot is not None:
        shot.generated_video_file_id = file_obj.id

    await sync_usage_from_shot_context(
        session,
        file_id=file_obj.id,
        shot_id=shot_id,
        usage_kind=FileUsageKind.generated_video,
        source_ref=f"shot:{shot_id}:generated_video",
    )

    return file_obj


async def run_video_generation_task(
    task_id: str,
    run_args: dict,
) -> None:
    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, 10)
            await session.commit()
            log_task_event("video_generation", task_id, "running")
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("video_generation", task_id, "cancelled", stage="before_execute")
                return

            provider = str(run_args.get("provider") or "")
            api_key = str(run_args.get("api_key") or "")
            base_url = run_args.get("base_url")
            input_dict = dict(run_args.get("input") or {})

            task = VideoGenerationTask(
                provider_config=ProviderConfig(
                    provider=provider,  # type: ignore[arg-type]
                    api_key=api_key,
                    base_url=base_url,
                ),
                input_=VideoGenerationInput.model_validate(input_dict),
            )
            await task.run()
            result = await task.get_result()
            if result is None:
                status_dict = await task.status()
                detailed_error = ""
                if isinstance(status_dict, dict):
                    detailed_error = str(status_dict.get("error") or "")
                msg = detailed_error or "Video generation task returned no result"
                raise RuntimeError(msg)
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("video_generation", task_id, "cancelled", stage="after_execute")
                return

            shot_id = str(run_args.get("shot_id") or "")
            if not shot_id:
                raise RuntimeError("run_args missing shot_id for video persistence")

            file_obj = await persist_generated_video_to_shot(
                session,
                task_id=task_id,
                shot_id=shot_id,
                result=result,
                provider=provider,
                api_key=api_key,
            )

            result_payload = result.model_dump()
            result_payload["file_id"] = file_obj.id
            await store.set_result(task_id, result_payload)
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("video_generation", task_id, "cancelled", stage="after_persist")
                return
            await store.set_progress(task_id, 100)
            await store.set_status(task_id, TaskStatus.succeeded)
            await recompute_shot_status(session, shot_id=shot_id)
            await session.commit()
            log_task_event("video_generation", task_id, "succeeded")
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with async_session_maker() as s2:
                store = SqlAlchemyTaskStore(s2)
                await store.set_error(task_id, str(exc))
                await store.set_status(task_id, TaskStatus.failed)
                shot_id = str(run_args.get("shot_id") or "")
                if shot_id:
                    await recompute_shot_status(s2, shot_id=shot_id)
                await s2.commit()
            log_task_failure("video_generation", task_id, str(exc))
