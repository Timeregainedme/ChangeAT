from __future__ import annotations

"""音频（TTS）生成任务的创建与执行落库。

与 `image_task_runner.py` 对称：创建 GenerationTaskLink，执行时下载产物写入 files。
音频不强制归属某个业务实体，relation_type/relation_entity_id 可为空；若传了
project_id 则额外登记 FileUsage（usage_kind=generated_audio）。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.audio_generation import AudioGenerationInput, AudioGenerationResult
from app.core.contracts.provider import ProviderConfig
from app.core.db import async_session_maker
from app.core.task_manager import DeliveryMode, SqlAlchemyTaskStore, TaskManager
from app.core.task_manager.types import TaskStatus
from app.core.tasks import AudioGenerationTask
from app.models.studio import FileItem
from app.models.task_links import GenerationTaskLink
from app.models.types import FileUsageKind
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


async def create_audio_task_and_link(
    *,
    db: AsyncSession,
    model_id: str | None,
    text: str,
    relation_type: str = "standalone",
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
) -> str:
    """创建音频生成任务，并建立任务关联。"""
    store = SqlAlchemyTaskStore(db)
    tm = TaskManager(store=store, strategies={})

    model = await resolve_audio_model(db, model_id)
    provider_cfg = await load_audio_provider_config(db, model.provider_id)

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
