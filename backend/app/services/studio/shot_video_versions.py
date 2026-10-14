"""镜头视频生成版本（抽卡历史）服务。

设计要点（对齐 Toonflow 的「候选 / 采用」分离）：

- 每一次视频生成任务就是一个**版本**，其提示词、画幅、时长与产出文件都随任务留存，
  后续重抽不会回写、也不会销毁旧版本；
- 「采用」只是把 `shots.generated_video_file_id` 指向某个版本的文件，
  因此最新一版自动生效，历史版本仍可随时切回；
- 版本列表只认属于该镜头的视频任务，避免把别处的文件挂上来。

本模块只负责读写这两件事，不负责发起生成。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import Shot
from app.models.task import GenerationTask
from app.models.task_links import GenerationTaskLink
from app.schemas.studio.shots import ShotVideoVersionRead
from app.services.common import entity_not_found

VIDEO_RESOURCE_TYPE = "video"
VIDEO_RELATION_TYPE = "video"
VIDEO_TASK_KIND = "video_generation"


def _enum_text(value: Any) -> str:
    """DB 里取出的枚举列是普通 str，也可能是 Enum，统一转成文本。"""
    return str(getattr(value, "value", value) or "")


def _run_args(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    run_args = payload.get("run_args")
    return run_args if isinstance(run_args, dict) else {}


def _version_input(payload: Any) -> dict[str, Any]:
    """取出实际提交给视频模型的那份入参。"""
    input_payload = _run_args(payload).get("input")
    return input_payload if isinstance(input_payload, dict) else {}


def _version_prompt(payload: Any) -> str | None:
    """版本提示词：优先取真正下发的那一份，其次取预览快照。"""
    submitted = str(_version_input(payload).get("prompt") or "").strip()
    if submitted:
        return submitted
    preview = _run_args(payload).get("prompt_preview")
    if isinstance(preview, dict):
        fallback = str(preview.get("prompt") or "").strip()
        if fallback:
            return fallback
    return None


def _version_seconds(payload: Any) -> float | None:
    raw = _version_input(payload).get("seconds")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def list_shot_video_versions(
    db: AsyncSession,
    *,
    shot_id: str,
) -> list[ShotVideoVersionRead]:
    """列出该镜头的全部视频版本，按创建时间倒序。"""
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise ValueError(entity_not_found("Shot"))

    # 先只取「窄」的排序键，再按 id 回表读宽行。原实现
    # `select(GenerationTaskLink, GenerationTask)` 会把 `payload` / `result`
    # 两个大文本列一起塞进 filesort，行一宽就撞上 MySQL 的
    # `(1038, 'Out of sort memory, consider increasing server sort buffer size')`，
    # 版本列表接口直接 500。排序在窄列上完成后，回表不再需要排序。
    ordered = (
        await db.execute(
            select(GenerationTaskLink.id, GenerationTaskLink.task_id)
            .join(GenerationTask, GenerationTask.id == GenerationTaskLink.task_id)
            .where(
                GenerationTaskLink.resource_type == VIDEO_RESOURCE_TYPE,
                GenerationTaskLink.relation_type == VIDEO_RELATION_TYPE,
                GenerationTaskLink.relation_entity_id == shot_id,
                GenerationTask.task_kind == VIDEO_TASK_KIND,
            )
            .order_by(GenerationTask.created_at.desc(), GenerationTask.id.desc())
        )
    ).all()
    link_ids = [row[0] for row in ordered]
    task_ids = [row[1] for row in ordered]

    links: dict[str, GenerationTaskLink] = {}
    tasks: dict[str, GenerationTask] = {}
    if link_ids:
        links = {
            item.id: item
            for item in (
                await db.execute(
                    select(GenerationTaskLink).where(GenerationTaskLink.id.in_(link_ids))
                )
            )
            .scalars()
            .all()
        }
    if task_ids:
        tasks = {
            item.id: item
            for item in (
                await db.execute(select(GenerationTask).where(GenerationTask.id.in_(task_ids)))
            )
            .scalars()
            .all()
        }

    current_file_id = str(shot.generated_video_file_id or "").strip() or None

    versions: list[ShotVideoVersionRead] = []
    for link_id, task_id in ordered:
        link = links.get(link_id)
        task = tasks.get(task_id)
        if link is None or task is None:
            continue
        file_id = str(link.file_id or "").strip() or None
        versions.append(
            ShotVideoVersionRead(
                task_id=task.id,
                file_id=file_id,
                status=_enum_text(task.status),
                is_current=bool(file_id and current_file_id and file_id == current_file_id),
                ratio=str(_version_input(task.payload).get("ratio") or "").strip() or None,
                seconds=_version_seconds(task.payload),
                prompt=_version_prompt(task.payload),
                error=str(task.error or "").strip() or None,
                created_at=task.created_at,
            )
        )
    return versions


async def adopt_shot_video_version(
    db: AsyncSession,
    *,
    shot_id: str,
    file_id: str,
) -> Shot:
    """把镜头当前采用的视频版本切到指定文件。

    只允许切到该镜头自己的历史版本；切换不删除任何旧版本文件。
    """
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise ValueError(entity_not_found("Shot"))

    target = str(file_id or "").strip()
    if not target:
        raise ValueError("file_id is required")

    allowed_stmt = select(GenerationTaskLink.file_id).where(
        GenerationTaskLink.resource_type == VIDEO_RESOURCE_TYPE,
        GenerationTaskLink.relation_type == VIDEO_RELATION_TYPE,
        GenerationTaskLink.relation_entity_id == shot_id,
        GenerationTaskLink.file_id.is_not(None),
    )
    allowed = {str(value).strip() for value in (await db.execute(allowed_stmt)).scalars().all() if value}
    if target not in allowed:
        raise ValueError("file_id is not a generated video version of this shot")

    shot.generated_video_file_id = target
    await db.flush()
    return shot
