"""镜头对白服务：ShotDialogLine 的分页查询与 CRUD。

显示名口径（全仓库唯一实现，分页列表 / 准备页聚合 / 时间轴字幕统一复用，
避免各展示链路各写一套兜底后互相漂移）：

- 台词行能解析到 ``speaker_character_id`` / ``target_character_id`` 时，显示角色表里的
  **当前**名字（角色改名后立即生效，不再显示行内历史旧名）；
- 解析不到（未关联角色、角色已删除、角色名为空）才回落到行内保存的
  ``speaker_name`` / ``target_name``；
- 解析只发生在展示层，不回写数据库，避免历史行内名字被静默抹掉。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import apply_keyword_filter, apply_order, paginate
from app.models.studio import Character, ShotDetail, ShotDialogLine
from app.schemas.common import ApiResponse, PaginatedData, paginated_response
from app.schemas.studio.shots import ShotDialogLineCreate, ShotDialogLineRead, ShotDialogLineUpdate
from app.services.studio.shot_extracted_dialogue_candidates import mark_pending_by_linked_dialog_line
from app.services.common import (
    create_and_refresh,
    entity_not_found,
    flush_and_refresh,
    get_or_404,
    patch_model,
    require_entity,
    require_optional_entity,
)


def pick_display_name(
    name_map: Mapping[str, str],
    *,
    character_id: str | None,
    fallback_name: str | None,
) -> str | None:
    """按「显示角色真名」口径挑选单个显示名。

    参数：
        name_map：角色 ID → 角色当前真名的映射，由 :func:`load_character_display_names` 批量查询得到。
        character_id：台词行上关联的角色 ID，可为空。
        fallback_name：行内保存的名字；解析不到角色时原样回落。

    返回：
        角色真名，或原样返回 ``fallback_name``。

    说明：
        这里刻意不做 ``fallback_name or ...`` 这类空串归一，否则同一字段会在
        ``""`` 与 ``None`` 之间漂移（D-1）：入参是空串就返回空串，是 ``None``
        就返回 ``None``，由调用方按各自契约决定空值展示。
    """
    resolved = name_map.get(character_id) if character_id else None
    return resolved or fallback_name


async def load_character_display_names(
    db: AsyncSession,
    *,
    character_ids: Iterable[str | None],
) -> dict[str, str]:
    """批量查询角色当前真名，供展示层统一解析使用。

    参数：
        character_ids：需要查询的角色 ID 集合（允许包含 ``None`` 与重复值）。

    返回：
        角色 ID → 角色名映射；只保留名字非空的角色，查不到的角色不会出现在映射里。
    """
    ids = {character_id for character_id in character_ids if character_id}
    if not ids:
        return {}
    rows = (
        await db.execute(select(Character).where(Character.id.in_(ids)))
    ).scalars().all()
    return {row.id: row.name for row in rows if row.name}


async def to_display_reads(
    db: AsyncSession,
    rows: Sequence[ShotDialogLine],
) -> list[ShotDialogLineRead]:
    """把台词行组装为带显示名的读模型（统一口径，不回写数据库）。

    参数：
        rows：``ShotDialogLine`` 行，通常来自分页查询或按镜头全量查询。

    返回：
        ``ShotDialogLineRead`` 列表，``speaker_name`` / ``target_name`` 已按
        「角色真名优先、行内名字兜底」解析。
    """
    name_map = await load_character_display_names(
        db,
        character_ids=[
            character_id
            for row in rows
            for character_id in (row.speaker_character_id, row.target_character_id)
        ],
    )
    return [
        ShotDialogLineRead.model_validate(row).model_copy(
            update={
                "speaker_name": pick_display_name(
                    name_map,
                    character_id=row.speaker_character_id,
                    fallback_name=row.speaker_name,
                ),
                "target_name": pick_display_name(
                    name_map,
                    character_id=row.target_character_id,
                    fallback_name=row.target_name,
                ),
            }
        )
        for row in rows
    ]


async def list_paginated(
    db: AsyncSession,
    *,
    shot_detail_id: str | None,
    q: str | None,
    order: str | None,
    is_desc: bool,
    page: int,
    page_size: int,
    allow_fields: set[str],
) -> ApiResponse[PaginatedData[ShotDialogLineRead]]:
    """分页查询镜头对白（显示名走统一口径）。"""
    stmt = select(ShotDialogLine)
    if shot_detail_id is not None:
        stmt = stmt.where(ShotDialogLine.shot_detail_id == shot_detail_id)
    stmt = apply_keyword_filter(stmt, q=q, fields=[ShotDialogLine.text])
    stmt = apply_order(
        stmt,
        model=ShotDialogLine,
        order=order,
        is_desc=is_desc,
        allow_fields=allow_fields,
        default="index",
    )
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)
    reads = await to_display_reads(db, items)
    return paginated_response(
        reads,
        page=page,
        page_size=page_size,
        total=total,
    )


async def list_by_shot(
    db: AsyncSession,
    *,
    shot_id: str,
) -> list[ShotDialogLineRead]:
    """按镜头读取全部已保存对白（含统一口径的显示名），供准备页聚合状态复用。

    返回读模型而非 ORM 行：准备页/时间轴等展示链路必须与分页列表走同一显示名口径，
    避免出现「列表显示真名、准备页显示未知」的分裂。
    """
    stmt = (
        select(ShotDialogLine)
        .where(ShotDialogLine.shot_detail_id == shot_id)
        .order_by(ShotDialogLine.index.asc(), ShotDialogLine.id.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return await to_display_reads(db, rows)


async def create(
    db: AsyncSession,
    *,
    body: ShotDialogLineCreate,
) -> ShotDialogLine:
    """创建镜头对白。"""
    await require_entity(db, ShotDetail, body.shot_detail_id, detail=entity_not_found("ShotDetail"), status_code=400)
    await require_optional_entity(
        db, Character, body.speaker_character_id, detail=entity_not_found("Character"), status_code=400
    )
    await require_optional_entity(
        db, Character, body.target_character_id, detail=entity_not_found("Character"), status_code=400
    )
    return await create_and_refresh(db, ShotDialogLine(**body.model_dump()))


async def update(
    db: AsyncSession,
    *,
    line_id: int,
    body: ShotDialogLineUpdate,
) -> ShotDialogLine:
    """更新镜头对白。"""
    obj = await get_or_404(db, ShotDialogLine, line_id, detail=entity_not_found("ShotDialogLine"))
    update_data = body.model_dump(exclude_unset=True)
    if "speaker_character_id" in update_data:
        await require_optional_entity(
            db, Character, update_data["speaker_character_id"], detail=entity_not_found("Character"), status_code=400
        )
    if "target_character_id" in update_data:
        await require_optional_entity(
            db, Character, update_data["target_character_id"], detail=entity_not_found("Character"), status_code=400
        )
    patch_model(obj, update_data)
    return await flush_and_refresh(db, obj)


async def delete(
    db: AsyncSession,
    *,
    line_id: int,
) -> None:
    """删除镜头对白。"""
    obj = await db.get(ShotDialogLine, line_id)
    if obj is None:
        return None
    await mark_pending_by_linked_dialog_line(db, dialog_line_id=obj.id)
    await db.delete(obj)
    await db.flush()
    return None
