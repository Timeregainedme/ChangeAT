from __future__ import annotations

"""音频（TTS）生成任务的创建与执行落库。

与 `image_task_runner.py` 对称：创建 GenerationTaskLink，执行时下载产物写入 files。
音频不强制归属某个业务实体，relation_type/relation_entity_id 可为空；若传了
project_id 则额外登记 FileUsage（usage_kind=generated_audio）。
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.audio_generation import AudioGenerationInput, AudioGenerationResult
from app.core.contracts.provider import ProviderConfig
from app.core.db import async_session_maker
from app.core.integrations.audio_capabilities import resolve_audio_capability, validate_audio_options
from app.core.task_manager import DeliveryMode, SqlAlchemyTaskStore, TaskManager
from app.core.task_manager.types import TaskStatus
from app.core.tasks import AudioGenerationTask
from app.models.studio import Character, FileItem, Shot, ShotDialogLine
from app.models.task_links import GenerationTaskLink
from app.models.types import FileUsageKind
from app.services.common.errors import entity_not_found
from app.services.studio.audio_tasks import load_audio_provider_config, resolve_audio_model
from app.services.studio.file_usages import upsert_file_usage
from app.services.studio.image_task_runner import _CreateOnlyTask
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_logging import log_task_event, log_task_failure
from app.utils.files import create_file_from_url_or_b64

__all__ = [
    "create_audio_task_and_link",
    "persist_generated_audio",
    "run_audio_generation_task",
]


async def _attach_audio_to_target(
    session: AsyncSession,
    *,
    relation_type: str,
    relation_entity_id: str,
    file_id: str,
) -> None:
    """把生成音频挂载到分镜或台词行（视频侧对称字段是 shots.generated_video_file_id）。"""
    if not relation_entity_id:
        return
    if relation_type == "shot":
        shot = await session.get(Shot, relation_entity_id)
        if shot is not None:
            shot.generated_audio_file_id = file_id
        return
    if relation_type == "dialog_line":
        try:
            line_id = int(relation_entity_id)
        except (TypeError, ValueError):
            return
        line = await session.get(ShotDialogLine, line_id)
        if line is not None:
            line.generated_audio_file_id = file_id


async def persist_generated_audio(
    session: AsyncSession,
    *,
    task_id: str,
    relation_type: str,
    relation_entity_id: str,
    result: AudioGenerationResult,
    project_id: str | None = None,
    chapter_id: str | None = None,
    shot_id: str | None = None,
) -> FileItem | None:
    """将音频生成结果落库为 files 行，并回填 GenerationTaskLink.file_id。"""
    url = (result.url or "").strip()
    if not url:
        return None

    file_obj = await create_file_from_url_or_b64(
        session,
        url=url,
        name=f"{relation_type or 'audio'}-{relation_entity_id or task_id}",
        prefix=f"generated-audios/{relation_type or 'standalone'}/{relation_entity_id or task_id}",
    )

    link_stmt = (
        select(GenerationTaskLink)
        .where(
            GenerationTaskLink.task_id == task_id,
            GenerationTaskLink.resource_type == "audio",
            GenerationTaskLink.relation_type == relation_type,
            GenerationTaskLink.relation_entity_id == relation_entity_id,
        )
        .limit(1)
    )
    link_row = (await session.execute(link_stmt)).scalars().first()
    if link_row is not None:
        link_row.file_id = file_obj.id

    await _attach_audio_to_target(
        session,
        relation_type=relation_type,
        relation_entity_id=relation_entity_id,
        file_id=file_obj.id,
    )

    if project_id:
        await upsert_file_usage(
            session,
            file_id=file_obj.id,
            project_id=project_id,
            chapter_id=chapter_id,
            shot_id=shot_id,
            usage_kind=FileUsageKind.generated_audio,
            source_ref=f"audio_task:{task_id}",
        )

    return file_obj


async def _resolve_audio_target(
    db: AsyncSession,
    *,
    text: str | None,
    dialog_line_id: int | None,
    shot_id: str | None,
    relation_type: str,
    relation_entity_id: str,
    speaker_character_id: str | None,
) -> tuple[str, str | None, str, str, str | None, str | None]:
    """推导本次配音的文本、挂载目标、说话角色与情绪。

    传 `dialog_line_id` 时可只给台词行 ID：文本、说话角色、关联目标、情绪全部自动带出，
    避免前端为每句台词重复提交一遍台词内容。

    返回的最后一个值是台词行上的 `emotion`（自然语言情绪/语气，F：接 TTS），
    没有台词行或台词行未填情绪时为 None。
    """
    line_emotion: str | None = None
    if dialog_line_id is not None:
        line = await db.get(ShotDialogLine, dialog_line_id)
        if line is None:
            raise HTTPException(status_code=404, detail=entity_not_found("ShotDialogLine"))
        if not text:
            text = line.text
        if speaker_character_id is None:
            speaker_character_id = line.speaker_character_id
        if not shot_id:
            shot_id = line.shot_detail_id
        # F：台词行的情绪自动带给 TTS，避免每句都要前端再传一遍。
        line_emotion = (getattr(line, "emotion", "") or "").strip() or None
        # 传了 dialog_line_id 就以台词行为挂载目标，避免与默认的 standalone 冲突。
        relation_type = "dialog_line"
        relation_entity_id = str(line.id)
    elif not relation_type:
        relation_type = "shot" if shot_id else "standalone"
    if relation_type == "shot" and not relation_entity_id and shot_id:
        relation_entity_id = shot_id

    resolved_text = (text or "").strip()
    if not resolved_text:
        raise HTTPException(
            status_code=422,
            detail="text is required：请提供 text，或提供 dialog_line_id 以复用台词文本",
        )
    if relation_type in {"shot", "dialog_line"} and not relation_entity_id:
        raise HTTPException(
            status_code=422,
            detail=f"relation_entity_id is required when relation_type={relation_type!r}",
        )
    return resolved_text, shot_id, relation_type, relation_entity_id, speaker_character_id, line_emotion


async def _resolve_audio_voice(
    db: AsyncSession,
    *,
    voice: str | None,
    voice_source: str | None,
    speaker_character_id: str | None,
) -> tuple[str | None, str | None]:
    """音色解析：显式 voice 优先，其次回落说话角色配置的默认音色（评审 R-08）。"""
    resolved_voice = (voice or "").strip() or None
    resolved_source = (voice_source or "").strip() or None
    if resolved_voice or not speaker_character_id:
        return resolved_voice, resolved_source

    character = await db.get(Character, speaker_character_id)
    if character is None:
        return None, resolved_source
    character_voice = (character.voice_id or "").strip() or None
    if character_voice:
        resolved_voice = character_voice
        if not resolved_source:
            resolved_source = (character.voice_source or "").strip() or None
    return resolved_voice, resolved_source


def _validate_audio_request(
    *,
    provider: str,
    model_name: str,
    text: str,
    voice: str | None,
    voice_source: str | None,
    language: str | None,
    speed: float | None,
    emotion: str | None,
    audio_format: str | None,
) -> None:
    """请求期音频参数校验（评审 R-20）。

    此前这些约束只在 Celery 任务里由适配层校验，导致接口先返回 201、任务随后必然
    失败，用户看到的是「创建成功但生成失败」。这里前移为 422，并给出可操作文案。
    """
    capability = resolve_audio_capability(provider=provider, model=model_name)
    label = f"provider={provider} model={model_name}"

    # 先校验纯输入约束（文本长度 / 语速区间 / 情感长度 / 格式），再校验音色要求。
    # 顺序很重要：若先报「voice is required」，用户就看不到真正的问题（例如文本超长、语速越界）。
    try:
        validate_audio_options(
            provider=provider,
            model=model_name,
            input_=AudioGenerationInput(
                text=text,
                model=model_name,
                voice=voice,
                voice_source=voice_source,
                language=language,
                speed=speed,
                emotion=emotion,
                format=audio_format or "wav",
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not voice and capability.supports_voice:
        raise HTTPException(
            status_code=422,
            detail=(
                f"voice is required for {label}：请显式传入 voice，"
                "或先为说话角色配置 characters.voice_id"
                "（可用 GET /studio/audio-tasks/voices 查询可用音色）"
            ),
        )
    if voice_source == "custom" and not capability.supports_custom_voice:
        raise HTTPException(
            status_code=422,
            detail=f"voice_source=custom is not supported by {label}",
        )


async def create_audio_task_and_link(
    *,
    db: AsyncSession,
    model_id: str | None,
    text: str | None = None,
    relation_type: str = "",
    relation_entity_id: str = "",
    voice: str | None = None,
    voice_source: str | None = None,
    language: str | None = None,
    speed: float | None = None,
    emotion: str | None = None,
    audio_format: str | None = None,
    project_id: str | None = None,
    chapter_id: str | None = None,
    shot_id: str | None = None,
    dialog_line_id: int | None = None,
    speaker_character_id: str | None = None,
) -> str:
    """创建音频生成任务，并建立任务关联。

    挂载粒度：
    - `dialog_line_id`：台词行级配音，产物回填 `shot_dialog_lines.generated_audio_file_id`
      （一个分镜多句台词、每句一个音色，各自独立）；
    - `shot_id`：分镜级配音，产物回填 `shots.generated_audio_file_id`；
    - 都不传：standalone，仅落库为文件，不挂载到分镜。

    音色解析顺序：显式 `voice` → 说话角色的 `characters.voice_id` → 报错（422）。
    """
    (
        resolved_text,
        resolved_shot_id,
        resolved_relation_type,
        resolved_relation_entity_id,
        resolved_speaker,
        resolved_emotion,
    ) = await _resolve_audio_target(
        db,
        text=text,
        dialog_line_id=dialog_line_id,
        shot_id=shot_id,
        relation_type=relation_type,
        relation_entity_id=relation_entity_id,
        speaker_character_id=speaker_character_id,
    )

    # F：显式传入的 emotion 优先；没传则用台词行上的 emotion。
    emotion = (emotion or "").strip() or resolved_emotion

    model = await resolve_audio_model(db, model_id)
    provider_cfg = await load_audio_provider_config(db, model.provider_id)

    resolved_voice, resolved_voice_source = await _resolve_audio_voice(
        db,
        voice=voice,
        voice_source=voice_source,
        speaker_character_id=resolved_speaker,
    )
    _validate_audio_request(
        provider=provider_cfg.provider,
        model_name=model.name,
        text=resolved_text,
        voice=resolved_voice,
        voice_source=resolved_voice_source,
        language=language,
        speed=speed,
        emotion=emotion,
        audio_format=audio_format,
    )

    text = resolved_text
    voice = resolved_voice
    voice_source = resolved_voice_source
    shot_id = resolved_shot_id
    relation_type = resolved_relation_type
    relation_entity_id = resolved_relation_entity_id

    store = SqlAlchemyTaskStore(db)
    tm = TaskManager(store=store, strategies={})

    input_payload: dict = {
        "text": text,
        "model": model.name,
    }
    if voice:
        input_payload["voice"] = voice
    if voice_source:
        input_payload["voice_source"] = voice_source
    if language:
        input_payload["language"] = language
    if speed is not None:
        input_payload["speed"] = speed
    if emotion:
        input_payload["emotion"] = emotion
    if audio_format:
        input_payload["format"] = audio_format

    run_args: dict = {
        "provider": provider_cfg.provider,
        "api_key": provider_cfg.api_key,
        "base_url": provider_cfg.base_url,
        "relation_type": relation_type,
        "relation_entity_id": relation_entity_id,
        "input": input_payload,
    }
    if project_id:
        run_args["project_id"] = project_id
    if chapter_id:
        run_args["chapter_id"] = chapter_id
    if shot_id:
        run_args["shot_id"] = shot_id

    task_record = await tm.create(
        task=_CreateOnlyTask(),
        mode=DeliveryMode.async_polling,
        task_kind="audio_generation",
        run_args=run_args,
    )

    db.add(
        GenerationTaskLink(
            task_id=task_record.id,
            resource_type="audio",
            relation_type=relation_type,
            relation_entity_id=relation_entity_id,
        )
    )
    await db.commit()

    from app.tasks.execute_task import enqueue_task_execution

    enqueue_task_execution(task_record.id)
    return task_record.id


async def run_audio_generation_task(
    task_id: str,
    run_args: dict,
) -> None:
    relation_type = str(run_args.get("relation_type") or "")
    relation_entity_id = str(run_args.get("relation_entity_id") or "")

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, 10)
            await session.commit()
            log_task_event("audio_generation", task_id, "running")
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("audio_generation", task_id, "cancelled", stage="before_execute")
                return

            provider = str(run_args.get("provider") or "")
            api_key = str(run_args.get("api_key") or "")
            base_url = run_args.get("base_url")
            input_dict = dict(run_args.get("input") or {})

            task = AudioGenerationTask(
                provider_config=ProviderConfig(
                    provider=provider,  # type: ignore[arg-type]
                    api_key=api_key,
                    base_url=base_url,
                ),
                input_=AudioGenerationInput.model_validate(input_dict),
            )
            await task.run()
            result = await task.get_result()
            if result is None:
                status_dict = await task.status()
                detailed_error = ""
                if isinstance(status_dict, dict):
                    detailed_error = str(status_dict.get("error") or "")
                raise RuntimeError(detailed_error or "Audio generation task returned no result")
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("audio_generation", task_id, "cancelled", stage="after_execute")
                return

            file_obj = await persist_generated_audio(
                session,
                task_id=task_id,
                relation_type=relation_type,
                relation_entity_id=relation_entity_id,
                result=result,
                project_id=(str(run_args.get("project_id") or "") or None),
                chapter_id=(str(run_args.get("chapter_id") or "") or None),
                shot_id=(str(run_args.get("shot_id") or "") or None),
            )

            result_payload = result.model_dump()
            if file_obj is not None:
                result_payload["file_id"] = file_obj.id
            await store.set_result(task_id, result_payload)
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("audio_generation", task_id, "cancelled", stage="after_persist")
                return
            await store.set_progress(task_id, 100)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event("audio_generation", task_id, "succeeded")
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with async_session_maker() as s2:
                store = SqlAlchemyTaskStore(s2)
                await store.set_error(task_id, str(exc))
                await store.set_status(task_id, TaskStatus.failed)
                await s2.commit()
            log_task_failure("audio_generation", task_id, str(exc))
