"""实体合并：把一个实体并入另一个同类型实体（数据库层，非 LLM 语义合并）。

为什么需要：
    提取阶段 LLM 存在「命名漂移」，同一个实体可能被写成多个名字
    （例如「护工护理工作服」与「护工工作服」），于是库里出现两条资产、
    两套图片、分别关联到不同镜头。用户需要一个入口把它们合成一条。

与 `script-processing/merge-entities` 的区别：
    那个是 **LLM 驱动**的「把多镜头提取结果合并成实体库」，发生在资产落库之前；
    本模块是 **数据库层**的「把两条已存在的实体记录合成一条」，用在资产已落库之后。

合并策略（保守、可审计、可回滚）：
1. 校验：同类型、都存在、ID 不同；
2. 迁移图片：源实体的 `*_images` 改挂到目标；主图冲突时只保留一张 `is_primary=True`；
3. 迁移关联：项目/章节/镜头关联改挂到目标；目标已存在同作用域关联时删除源的多余关联；
4. 迁移交叉引用：见 `_CROSS_REFS`（例如台词说话人、镜头的场景、角色的演员/服装、角色道具绑定）；
5. 迁移提取候选：`shot_extracted_candidates.linked_entity_id` 指向目标；
6. 删除源实体；
7. 全过程在调用方事务内完成（`get_db` 统一 commit/rollback），失败即整体回滚。

重要约束：
    `character_prop_links` / `shot_character_links` 有 (owner_id, index) 唯一约束，
    因此迁移关联时不能只改外键，必要时需要重排 index。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import (
    Character,
    CharacterPropLink,
    ProjectActorLink,
    ProjectCostumeLink,
    ProjectPropLink,
    ProjectSceneLink,
    ShotCharacterLink,
    ShotDetail,
    ShotDialogLine,
    ShotExtractedCandidate,
)
from app.services.common import entity_not_found, get_or_404
from app.services.studio.entity_specs import LINK_MODEL_BY_ENTITY, entity_spec, normalize_entity_type

SUPPORTED_ENTITY_TYPES = frozenset({"actor", "character", "scene", "prop", "costume"})


async def merge_entities(
    db: AsyncSession,
    *,
    entity_type: str,
    source_id: str,
    target_id: str,
) -> dict[str, Any]:
    """把 `source_id` 实体合并进 `target_id` 实体，返回迁移统计。

    参数：
    - `entity_type`：actor / character / scene / prop / costume
    - `source_id`：被合并掉的一方（合并结束后该记录删除）
    - `target_id`：保留的一方

    返回：`images_moved` / `links_moved` / `links_dropped` /
    `cross_refs_moved` / `candidates_repointed` 等统计，便于前端展示与排查。
    """
    entity_type_norm = normalize_entity_type(entity_type)
    if entity_type_norm not in SUPPORTED_ENTITY_TYPES:
        # normalize_entity_type 已兜底，这里保留二次防御，避免未来放开类型时漏改。
        raise ValueError(f"不支持的实体类型：{entity_type}")
    if source_id == target_id:
        raise ValueError("不能把实体合并到它自己")
    if not source_id.strip() or not target_id.strip():
        raise ValueError("source_id 与 target_id 不能为空")

    spec = entity_spec(entity_type_norm)
    source = await get_or_404(
        db, spec.model, source_id, detail=entity_not_found(spec.model.__name__)
    )
    target = await get_or_404(
        db, spec.model, target_id, detail=entity_not_found(spec.model.__name__)
    )

    stats: dict[str, int] = {
        "images_moved": 0,
        "images_dropped": 0,
        "links_moved": 0,
        "links_dropped": 0,
        "cross_refs_moved": 0,
        "candidates_repointed": 0,
    }

    await _move_images(db, spec=spec, source_id=source_id, target_id=target_id, stats=stats)
    await _move_project_links(
        db,
        entity_type=entity_type_norm,
        source_id=source_id,
        target_id=target_id,
        stats=stats,
    )
    await _move_cross_refs(
        db,
        entity_type=entity_type_norm,
        source_id=source_id,
        target_id=target_id,
        stats=stats,
    )
    await _repoint_candidates(
        db,
        entity_type=entity_type_norm,
        source_id=source_id,
        target_id=target_id,
        stats=stats,
    )

    # 最后删除源实体：外键多为 CASCADE/SET NULL，此时其图片与关联已全部迁走或删除。
    await db.delete(source)
    await db.flush()

    return {
        "entity_type": entity_type_norm,
        "source_id": source_id,
        "target_id": target_id,
        **stats,
    }


async def _move_images(
    db: AsyncSession,
    *,
    spec: Any,
    source_id: str,
    target_id: str,
    stats: dict[str, int],
) -> None:
    """把源实体的图片改挂到目标实体，并处理两类冲突。

    冲突一：`(实体, quality_level, view_angle)` 唯一约束（所有 *_images 表都有）。
        → 目标已有同档同视角的图片时，**丢弃源的这张**（`images_dropped`）。
        取舍理由：合并方向由用户指定，默认认为目标侧素材是「要保留的那一套」；
        若真要留源图，用户可在合并前先手动删掉目标图，语义更可控。
    冲突二：主图唯一性（应用层约束，库表无唯一索引）。
        → 目标已有主图时，迁入的图片一律降级为非主图。

    不因冲突而中断合并：用户的目标是「把两条记录并掉」，个别同档视角重复
    不应让整个操作失败。
    """
    parent_field = getattr(spec.image_model, spec.id_field)

    target_images = (
        (await db.execute(select(spec.image_model).where(parent_field == target_id)))
        .scalars()
        .all()
    )
    taken_slots = {
        (getattr(row, "quality_level", None), getattr(row, "view_angle", None))
        for row in target_images
    }
    has_primary = any(bool(getattr(row, "is_primary", False)) for row in target_images)

    source_images = (
        (await db.execute(select(spec.image_model).where(parent_field == source_id)))
        .scalars()
        .all()
    )
    for row in source_images:
        slot = (getattr(row, "quality_level", None), getattr(row, "view_angle", None))
        if slot in taken_slots:
            await db.delete(row)
            stats["images_dropped"] += 1
            continue

        setattr(row, spec.id_field, target_id)
        taken_slots.add(slot)
        if getattr(row, "is_primary", False):
            if has_primary:
                row.is_primary = False
            else:
                has_primary = True
        stats["images_moved"] += 1

    if source_images:
        await db.flush()


async def _move_project_links(
    db: AsyncSession,
    *,
    entity_type: str,
    source_id: str,
    target_id: str,
    stats: dict[str, int],
) -> None:
    """迁移项目/章节/镜头级关联；同作用域已存在时删除源的多余关联。

    角色走 `shot_character_links`，其余走 `project_*_links`。
    两者都有唯一约束，因此必须先查目标已占用的作用域再决定「迁移」还是「丢弃」。
    """
    if entity_type == "character":
        src_links = (
            (await db.execute(select(ShotCharacterLink).where(ShotCharacterLink.character_id == source_id)))
            .scalars()
            .all()
        )
        taken_shot_ids = set(
            (
                await db.execute(
                    select(ShotCharacterLink.shot_id).where(ShotCharacterLink.character_id == target_id)
                )
            )
            .scalars()
            .all()
        )
        for link in src_links:
            if link.shot_id in taken_shot_ids:
                await db.delete(link)
                stats["links_dropped"] += 1
            else:
                link.character_id = target_id
                taken_shot_ids.add(link.shot_id)
                stats["links_moved"] += 1
        if src_links:
            await db.flush()
        return

    link_pair = LINK_MODEL_BY_ENTITY.get(entity_type)
    if link_pair is None:
        return
    link_model, asset_field = link_pair

    src_links = (
        (await db.execute(select(link_model).where(getattr(link_model, asset_field) == source_id)))
        .scalars()
        .all()
    )
    taken_scopes = {
        (row.project_id, row.chapter_id, row.shot_id)
        for row in (
            await db.execute(select(link_model).where(getattr(link_model, asset_field) == target_id))
        )
        .scalars()
        .all()
    }
    for link in src_links:
        scope = (link.project_id, link.chapter_id, link.shot_id)
        if scope in taken_scopes:
            await db.delete(link)
            stats["links_dropped"] += 1
        else:
            setattr(link, asset_field, target_id)
            taken_scopes.add(scope)
            stats["links_moved"] += 1
    if src_links:
        await db.flush()


async def _move_cross_refs(
    db: AsyncSession,
    *,
    entity_type: str,
    source_id: str,
    target_id: str,
    stats: dict[str, int],
) -> None:
    """迁移「其他业务表」对源实体的直接引用。

    这些引用不属于统一关联表，但从业务上看必须跟着合并走，否则会出现
    「资产合并了，但台词还是指向旧角色 / 镜头还是指向旧场景」这类悬挂引用。
    """
    if entity_type == "character":
        await _merge_character_cross_refs(db, source_id=source_id, target_id=target_id, stats=stats)
        return
    if entity_type == "scene":
        # 镜头的场景引用在 shot_details.scene_id（与 shots 共享主键）。
        details = (
            (await db.execute(select(ShotDetail).where(ShotDetail.scene_id == source_id)))
            .scalars()
            .all()
        )
        for detail in details:
            detail.scene_id = target_id
            stats["cross_refs_moved"] += 1
        if details:
            await db.flush()
        return
    if entity_type == "prop":
        await _merge_prop_cross_refs(db, source_id=source_id, target_id=target_id, stats=stats)
        return
    if entity_type == "costume":
        # 角色的服装引用（角色可指定默认服装）。
        characters = (
            (await db.execute(select(Character).where(Character.costume_id == source_id)))
            .scalars()
            .all()
        )
        for character in characters:
            character.costume_id = target_id
            stats["cross_refs_moved"] += 1
        if characters:
            await db.flush()
        return
    if entity_type == "actor":
        # 角色的演员引用。
        characters = (
            (await db.execute(select(Character).where(Character.actor_id == source_id)))
            .scalars()
            .all()
        )
        for character in characters:
            character.actor_id = target_id
            stats["cross_refs_moved"] += 1
        if characters:
            await db.flush()


async def _merge_character_cross_refs(
    db: AsyncSession,
    *,
    source_id: str,
    target_id: str,
    stats: dict[str, int],
) -> None:
    """角色合并时的交叉引用：台词说话人/对象 + 角色道具绑定（含 index 重排）。"""
    # 1. 台词说话人 / 对话对象。
    lines = (
        (
            await db.execute(
                select(ShotDialogLine).where(
                    (ShotDialogLine.speaker_character_id == source_id)
                    | (ShotDialogLine.target_character_id == source_id)
                )
            )
        )
        .scalars()
        .all()
    )
    for line in lines:
        if line.speaker_character_id == source_id:
            line.speaker_character_id = target_id
            stats["cross_refs_moved"] += 1
        if line.target_character_id == source_id:
            line.target_character_id = target_id
            stats["cross_refs_moved"] += 1
    if lines:
        await db.flush()

    # 2. 角色-道具绑定：目标已有同一道具时删源；否则改挂并重排 index。
    src_links = (
        (await db.execute(select(CharacterPropLink).where(CharacterPropLink.character_id == source_id)))
        .scalars()
        .all()
    )
    if not src_links:
        return
    target_links = (
        (await db.execute(select(CharacterPropLink).where(CharacterPropLink.character_id == target_id)))
        .scalars()
        .all()
    )
    taken_props = {row.prop_id for row in target_links}
    next_index = max((row.index for row in target_links), default=-1) + 1
    for link in src_links:
        if link.prop_id in taken_props:
            await db.delete(link)
            stats["links_dropped"] += 1
        else:
            link.character_id = target_id
            # index 是 (character_id, index) 唯一约束的一部分，必须避让目标已占用的序号。
            link.index = next_index
            next_index += 1
            taken_props.add(link.prop_id)
            stats["links_moved"] += 1
    await db.flush()


async def _merge_prop_cross_refs(
    db: AsyncSession,
    *,
    source_id: str,
    target_id: str,
    stats: dict[str, int],
) -> None:
    """道具合并时的交叉引用：角色-道具绑定（按 prop_id 去重）。"""
    src_links = (
        (await db.execute(select(CharacterPropLink).where(CharacterPropLink.prop_id == source_id)))
        .scalars()
        .all()
    )
    if not src_links:
        return
    taken_character_ids = set(
        (
            await db.execute(
                select(CharacterPropLink.character_id).where(CharacterPropLink.prop_id == target_id)
            )
        )
        .scalars()
        .all()
    )
    for link in src_links:
        if link.character_id in taken_character_ids:
            await db.delete(link)
            stats["links_dropped"] += 1
        else:
            # 同一角色下 index 不变：该行本来就占用这个 (character_id, index)，
            # 只改 prop_id 不会触发 (character_id, index) 唯一约束。
            link.prop_id = target_id
            taken_character_ids.add(link.character_id)
            stats["links_moved"] += 1
    await db.flush()


async def _repoint_candidates(
    db: AsyncSession,
    *,
    entity_type: str,
    source_id: str,
    target_id: str,
    stats: dict[str, int],
) -> None:
    """把已关联到源实体的提取候选项改为指向目标实体。

    候选有 (shot_id, candidate_type, candidate_name) 唯一约束，只改
    `linked_entity_id` 不会触发冲突。
    """
    candidates = (
        (
            await db.execute(
                select(ShotExtractedCandidate).where(
                    ShotExtractedCandidate.linked_entity_id == source_id,
                    ShotExtractedCandidate.candidate_type == entity_type,
                )
            )
        )
        .scalars()
        .all()
    )
    for candidate in candidates:
        candidate.linked_entity_id = target_id
        stats["candidates_repointed"] += 1
    if candidates:
        await db.flush()


__all__ = ["SUPPORTED_ENTITY_TYPES", "merge_entities"]
