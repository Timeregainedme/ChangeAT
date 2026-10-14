"""从提取候选批量创建资产并关联分镜的服务。

ToonFlow 式「一键提取资产」的核心落库步骤：
- 输入章节 ID（及可选的候选类型过滤）；
- 遍历该章节下所有 pending 提取候选（人物/场景/道具/服装）；
- 对每个候选：若项目内尚无同名实体则用候选 payload（description/voice_description 等）创建实体，
  并绑定到候选所在分镜；随后将候选标记为 linked；
- 同名实体已存在时直接关联已有实体，不重复创建。

返回逐候选的处理结果，供前端展示「新建 / 已关联 / 跳过」。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.common.errors import entity_not_found
from app.models.studio import (
    Chapter,
    Character,
    Costume,
    Prop,
    Scene,
    Shot,
    ShotExtractedCandidate,
)
from app.models.types import ShotCandidateStatus
from app.services.studio.entity_crud import create_entity
from app.services.studio.entity_specs import LINK_MODEL_BY_ENTITY
from app.services.studio.shot_extracted_candidates import mark_linked_by_name

# 候选类型 → 实体类型名（与 entities 路由的 entity_type 对齐）。
_CANDIDATE_ENTITY_TYPE: dict[str, str] = {
    "character": "character",
    "scene": "scene",
    "prop": "prop",
    "costume": "costume",
}

# 非 character 实体类型 → 项目关联表（用于按项目查重）。
_LINK_MODEL_BY_ENTITY_TYPE: dict[str, tuple[Any, str]] = {
    entity_type: (model, asset_field)
    for entity_type, (model, asset_field) in LINK_MODEL_BY_ENTITY.items()
    if entity_type in {"scene", "prop", "costume"}
}

# 实体 ID 前缀（与前端创建角色时的 char-xxx 风格保持一致）。
_ENTITY_ID_PREFIX: dict[str, str] = {
    "character": "char",
    "scene": "scene",
    "prop": "prop",
    "costume": "costume",
}


def _new_entity_id(entity_type: str) -> str:
    return f"{_ENTITY_ID_PREFIX[entity_type]}-{uuid.uuid4().hex[:8]}"


async def _find_existing_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    project_id: str,
    name: str,
) -> str | None:
    """按 (项目, 名称) 找同名实体，返回实体 ID；不存在返回 None。

    character 直接按 project_id+name 查；scene/prop/costume 无 project_id 字段，
    通过项目关联表（project_scene_links 等）限定项目范围后按 name 查重。
    """
    if entity_type == "character":
        model: Any = Character
        stmt = (
            select(model.id)
            .where(model.project_id == project_id)  # type: ignore[attr-defined]
            .where(model.name == name)
            .limit(1)
        )
    else:
        link_model, asset_field = _LINK_MODEL_BY_ENTITY_TYPE[entity_type]
        model = {"scene": Scene, "prop": Prop, "costume": Costume}[entity_type]
        entity_id_col = getattr(link_model, asset_field)
        stmt = (
            select(entity_id_col)
            .join(model, model.id == entity_id_col)
            .where(link_model.project_id == project_id)
            .where(model.name == name)
            .limit(1)
        )
    row = (await db.execute(stmt)).scalars().first()
    return str(row) if row is not None else None


async def _create_entity_from_candidate(
    db: AsyncSession,
    *,
    entity_type: str,
    project_id: str,
    name: str,
    payload: dict[str, Any],
    chapter_id: str,
    shot_id: str,
) -> str:
    """用候选 payload 创建实体并绑定到分镜，返回实体 ID。"""
    body: dict[str, Any] = {
        "id": _new_entity_id(entity_type),
        "project_id": project_id,
        "name": name,
        "description": str(payload.get("description") or "").strip(),
        "chapter_id": chapter_id,
        "shot_id": shot_id,
    }
    if entity_type == "character":
        voice_description = str(payload.get("voice_description") or "").strip()
        if voice_description:
            body["voice_description"] = voice_description
    created = await create_entity(db, entity_type=entity_type, body=body)
    return str(created.get("id") or body["id"])


async def create_assets_from_extraction_candidates(
    db: AsyncSession,
    *,
    chapter_id: str,
    types: list[str] | None = None,
) -> dict[str, Any]:
    """按章节一键创建/关联提取候选资产。

    返回结构：
    {
      "created": [{candidate_id, type, name, entity_id}],
      "linked":  [{candidate_id, type, name, entity_id}],
      "skipped": [{candidate_id, type, name, reason}],
    }
    """
    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        raise ValueError(entity_not_found("Chapter"))
    project_id = chapter.project_id

    allow_types = {str(x).strip().lower() for x in (types or [])}
    if allow_types:
        invalid = allow_types - set(_CANDIDATE_ENTITY_TYPE)
        if invalid:
            raise ValueError(f"unsupported candidate types: {sorted(invalid)}")

    # 章节下所有镜头 → 所有 pending 候选（按 shot、候选类型、名称排序保证确定性）
    shot_ids_stmt = select(Shot.id).where(Shot.chapter_id == chapter_id)
    shot_ids = [str(x) for x in (await db.execute(shot_ids_stmt)).scalars().all()]
    if not shot_ids:
        return {"created": [], "linked": [], "skipped": []}

    candidates_stmt = (
        select(ShotExtractedCandidate)
        .where(ShotExtractedCandidate.shot_id.in_(shot_ids))
        .where(ShotExtractedCandidate.candidate_status == ShotCandidateStatus.pending)
        .order_by(
            ShotExtractedCandidate.shot_id.asc(),
            ShotExtractedCandidate.candidate_type.asc(),
            ShotExtractedCandidate.candidate_name.asc(),
        )
    )
    candidates = list((await db.execute(candidates_stmt)).scalars().all())

    created: list[dict[str, Any]] = []
    linked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for cand in candidates:
        candidate_type = str(getattr(cand.candidate_type, "value", cand.candidate_type))
        if allow_types and candidate_type not in allow_types:
            continue
        entity_type = _CANDIDATE_ENTITY_TYPE[candidate_type]
        name = str(cand.candidate_name or "").strip()
        if not name:
            skipped.append({"candidate_id": cand.id, "type": candidate_type, "name": name, "reason": "empty name"})
            continue

        existing_id = await _find_existing_entity(db, entity_type=entity_type, project_id=project_id, name=name)
        payload = dict(cand.payload or {})
        try:
            if existing_id is None:
                entity_id = await _create_entity_from_candidate(
                    db,
                    entity_type=entity_type,
                    project_id=project_id,
                    name=name,
                    payload=payload,
                    chapter_id=chapter_id,
                    shot_id=cand.shot_id,
                )
                created.append({"candidate_id": cand.id, "type": candidate_type, "name": name, "entity_id": entity_id})
            else:
                entity_id = existing_id
                linked.append({"candidate_id": cand.id, "type": candidate_type, "name": name, "entity_id": entity_id})

            await mark_linked_by_name(
                db,
                shot_id=cand.shot_id,
                candidate_type=candidate_type,
                candidate_name=name,
                linked_entity_id=entity_id,
            )
        except Exception as exc:  # noqa: BLE001 - 单候选失败不阻断批量
            skipped.append({"candidate_id": cand.id, "type": candidate_type, "name": name, "reason": str(exc)})

    return {"created": created, "linked": linked, "skipped": skipped}
