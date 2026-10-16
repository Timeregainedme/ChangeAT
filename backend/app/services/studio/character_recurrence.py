"""角色「是否反复出现」的判定。

为什么需要单独一个模块：角色要不要绑定演员，取决于它是主角级人物还是只露一次面的配角 ——
跨多集反复出现的角色必须绑演员，否则同一个「人」在不同集里的长相会各演各的；
只在一集里出现一次的角色则不需要，强行要求只会让建角色卡变得繁琐。
用户口径（m09145）：「角色不用必须关联演员，主角才需要，只在一集内出现的不需要」。

判定依据是 `shot_character_links ⋈ shots.chapter_id` 的**去重章节数**，
而不是再加一个需要人工维护的「角色类型」字段：分镜关联本来就已经记录了角色出现在哪几集，
再让用户手填一遍既多余又会和实际分镜不一致。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import Chapter, Character
from app.models.studio_shots import Shot, ShotCharacterLink
from app.schemas.studio.projects import (
    CharacterRecurrenceRead,
    ProjectCharacterRecurrenceRead,
)

# 角色出现在多少个不同章节（集）以上，才算「主角级、需要绑定演员」。
RECURRING_MIN_CHAPTERS = 2


def is_recurring(chapter_count: int) -> bool:
    """章节数是否达到「反复出现」的门槛。

    为什么用函数而不是到处写 `>= 2`：阈值是业务口径，集中在这里改一处即可生效。
    """
    return chapter_count >= RECURRING_MIN_CHAPTERS


async def character_chapter_counts(db: AsyncSession, *, project_id: str) -> dict[str, int]:
    """按项目统计每个角色出现的**去重章节数**（角色 ID → 章节数）。

    未出现在任何章节的角色不会出现在返回结果里，调用方按 `counts.get(cid, 0)` 取用；
    「还没挂分镜」与「只在一集里出现」在这里都得到 0/1，待遇一致（都不需要绑演员）。
    """
    stmt = (
        select(ShotCharacterLink.character_id, func.count(func.distinct(Shot.chapter_id)))
        .join(Shot, Shot.id == ShotCharacterLink.shot_id)
        .join(Chapter, Chapter.id == Shot.chapter_id)
        .where(Chapter.project_id == project_id)
        .group_by(ShotCharacterLink.character_id)
    )
    rows = (await db.execute(stmt)).all()
    return {str(row[0]): int(row[1] or 0) for row in rows}


async def character_chapter_count(db: AsyncSession, *, character_id: str) -> int:
    """单个角色出现的去重章节数。

    生成角色图时用它决定「未绑定演员」要不要报警：主角级才提示，配角不打扰用户。
    """
    stmt = (
        select(func.count(func.distinct(Shot.chapter_id)))
        .select_from(ShotCharacterLink)
        .join(Shot, Shot.id == ShotCharacterLink.shot_id)
        .where(ShotCharacterLink.character_id == character_id)
    )
    return int(await db.scalar(stmt) or 0)


async def get_project_character_recurrence(
    db: AsyncSession, *, project_id: str
) -> ProjectCharacterRecurrenceRead:
    """组装项目下全部角色的跨集出现情况（含章节数为 0 的角色）。

    为什么要把 0 章节的角色也列出来：前端拿到的是一张完整的「角色 ID → 要不要绑演员」映射，
    缺项会让新建角色查不到自己而误判成主角级。
    """
    counts = await character_chapter_counts(db, project_id=project_id)
    character_ids = [
        str(item) for item in (await db.scalars(select(Character.id).where(Character.project_id == project_id))).all()
    ]
    items = [
        CharacterRecurrenceRead(
            character_id=character_id,
            chapter_count=counts.get(character_id, 0),
            recurring=is_recurring(counts.get(character_id, 0)),
        )
        for character_id in character_ids
    ]
    return ProjectCharacterRecurrenceRead(
        project_id=project_id, min_chapters=RECURRING_MIN_CHAPTERS, items=items
    )
