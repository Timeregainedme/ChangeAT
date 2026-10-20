from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.task_manager import DeliveryMode, SqlAlchemyTaskStore, TaskManager
from app.dependencies import get_db
from app.models.task_links import GenerationTaskLink
from app.schemas.common import ApiResponse, created_response
from app.services.film.shot_frame_prompt_tasks import (
    build_run_args as build_shot_frame_prompt_run_args,
    normalize_frame_type,
    relation_type_for_frame,
)
from app.services.studio.shot_status import mark_shot_generating
from app.tasks.execute_task import enqueue_task_execution

from app.services.common.workspace import resolve_workspace_id

from .common import (
    ShotFramePromptRequest,
    TaskCreated,
    _CreateOnlyTask,
)
router = APIRouter()


@router.post(
    "/tasks/shot-frame-prompts",
    response_model=ApiResponse[TaskCreated],
    status_code=201,
    summary="镜头分镜帧提示词生成（任务版）",
)
async def create_shot_frame_prompt_task(
    body: ShotFramePromptRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskCreated]:
    frame_type = normalize_frame_type(body.frame_type)
    relation_type = relation_type_for_frame(frame_type)

    store = SqlAlchemyTaskStore(db)
    tm = TaskManager(store=store, strategies={})
    run_args = await build_shot_frame_prompt_run_args(
        db,
        shot_id=body.shot_id,
        frame_type=frame_type,
    )

    workspace_id = await resolve_workspace_id(db, shot_id=body.shot_id)
    task_record = await tm.create(
        task=_CreateOnlyTask(),
        mode=DeliveryMode.async_polling,
        task_kind="shot_frame_prompt",
        run_args=run_args,
        workspace_id=workspace_id,
    )
    db.add(
        GenerationTaskLink(
            task_id=task_record.id,
            resource_type="prompt",
            relation_type=relation_type,
            relation_entity_id=body.shot_id,
        )
    )
    await mark_shot_generating(db, shot_id=body.shot_id)
    await db.commit()

    enqueue_task_execution(task_record.id)
    return created_response(TaskCreated(task_id=task_record.id))
