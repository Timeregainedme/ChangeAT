"""任务所属工作区的解析。

为什么需要这个模块：
`generation_tasks.workspace_id` 是 NOT NULL，但任务的创建入口分散在
    - `app/services/script_processing_tasks.py`（6 处）
    - `app/services/studio/image_task_runner.py`
    - `app/services/studio/audio_task_runner.py`
    - `app/services/film/generated_video.py`
    - `app/api/v1/routes/film/generated_video.py`、`tasks_images.py`
这些入口的业务入参各不相同（chapter_id / project_id / shot_id / 多态 relation_entity_id），
但任务归属总能由它已关联的业务实体唯一确定。集中在这里回溯，调用方无需感知租户概念。

为什么不兜底到默认工作区：
兜底会把无法判定归属的任务放进 `ws-default`，等于对默认租户泄露。
宁可抛错让创建失败 —— 调用方必须传一个真实存在的业务实体。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import Chapter, Project, Shot


async def _from_project(db: AsyncSession, project_id: str | None) -> str | None:
    if not project_id:
        return None
    return await db.scalar(select(Project.workspace_id).where(Project.id == project_id))


async def _from_chapter(db: AsyncSession, chapter_id: str | None) -> str | None:
    if not chapter_id:
        return None
    return await db.scalar(
        select(Project.workspace_id)
        .join(Chapter, Chapter.project_id == Project.id)
        .where(Chapter.id == chapter_id)
    )


async def _from_shot(db: AsyncSession, shot_id: str | None) -> str | None:
    if not shot_id:
        return None
    return await db.scalar(
        select(Project.workspace_id)
        .join(Chapter, Chapter.project_id == Project.id)
        .join(Shot, Shot.chapter_id == Chapter.id)
        .where(Shot.id == shot_id)
    )


async def resolve_workspace_id(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    chapter_id: str | None = None,
    shot_id: str | None = None,
    relation_entity_id: str | None = None,
) -> str:
    """解析任务所属工作区。

    参数：
    - `project_id` / `chapter_id` / `shot_id`：已知的业务实体 ID；
    - `relation_entity_id`：多态的关联实体 ID（可能是 project / chapter / shot），
      按「项目 → 章节 → 镜头」顺序探测。

    返回：
    - 命中的 `workspace_id`。

    失败语义：
    - 所有解释都查不到 → ValueError；
    - 多个解释指向不同工作区 → ValueError（说明数据被跨租户错误关联）。

    两者都会由 `app/main.py` 的 ValueError handler 转成 400，不会变成 500。
    """
    candidates: list[str] = []
    for resolved in (
        await _from_project(db, project_id),
        await _from_chapter(db, chapter_id),
        await _from_shot(db, shot_id),
        await _from_project(db, relation_entity_id),
        await _from_chapter(db, relation_entity_id),
        await _from_shot(db, relation_entity_id),
    ):
        if resolved:
            candidates.append(resolved)

    if not candidates:
        raise ValueError("无法确定任务所属工作区：关联的业务实体不存在")

    unique = set(candidates)
    if len(unique) > 1:
        raise ValueError("任务关联的业务实体分属不同工作区，拒绝创建")

    return candidates[0]
