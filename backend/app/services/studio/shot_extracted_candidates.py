"""镜头提取候选项服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.studio import (
    Chapter,
    Shot,
    ShotCandidateStatus,
    ShotCandidateType,
    ShotExtractedCandidate,
)
from app.schemas.skills.script_processing import StudioScriptExtractionDraft
from app.services.common import entity_not_found
from app.services.studio.shot_status import recompute_shot_status, recompute_shot_status_sync


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _flush_refresh_candidate(
    db: AsyncSession,
    row: ShotExtractedCandidate,
) -> ShotExtractedCandidate:
    """刷新 candidate，避免响应序列化时触发异步懒加载。"""
    await db.flush()
    await db.refresh(row)
    return row


async def list_by_shot(
    db: AsyncSession,
    *,
    shot_id: str,
) -> list[ShotExtractedCandidate]:
    stmt = (
        select(ShotExtractedCandidate)
        .where(ShotExtractedCandidate.shot_id == shot_id)
        .order_by(ShotExtractedCandidate.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


def _payload_from_asset(item: Any) -> dict[str, Any]:
    """从草稿资产抽取候选 payload。

    `costume_name` 必须一起带上：ElementExtractorAgent 的 characters 结构里本就有
    `costume_name?`（见 app/chains/agents/element_extractor_agent.py），
    `StudioScriptExtractionDraft.character.costume_name` 的注释也写明「导入时映射到
    costume_id」，而分镜准备页读出来时同样带着它（shot_extraction_draft.py）。
    此前这里只复制 5 个键把它丢掉，导致「一键创建资产」建出的角色从来不绑服装
    （用户需求 m08283）。scene/prop/costume 草稿没有该字段，getattr 返回 None 自动跳过。
    """
    payload: dict[str, Any] = {}
    for key in ("id", "file_id", "thumbnail", "description", "voice_description", "costume_name"):
        value = getattr(item, key, None)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        payload[key] = value
    return payload


def _build_candidates_from_shot_draft(
    shot_draft: Any,
    *,
    character_by_name: dict[str, Any] | None = None,
    scene_by_name: dict[str, Any] | None = None,
    prop_by_name: dict[str, Any] | None = None,
    costume_by_name: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if getattr(shot_draft, "scene_name", None):
        scene_name = str(shot_draft.scene_name).strip()
        scene_payload = _payload_from_asset((scene_by_name or {}).get(scene_name))
        candidates.append(
            {
                "candidate_type": ShotCandidateType.scene.value,
                "candidate_name": scene_name,
                "payload": scene_payload,
            }
        )
    for candidate_type, names, source_map in (
        (
            ShotCandidateType.character.value,
            list(getattr(shot_draft, "character_names", []) or []),
            character_by_name or {},
        ),
        (
            ShotCandidateType.prop.value,
            list(getattr(shot_draft, "prop_names", []) or []),
            prop_by_name or {},
        ),
        (
            ShotCandidateType.costume.value,
            list(getattr(shot_draft, "costume_names", []) or []),
            costume_by_name or {},
        ),
    ):
        for name in names:
            normalized_name = str(name).strip()
            if not normalized_name:
                continue
            candidates.append(
                {
                    "candidate_type": candidate_type,
                    "candidate_name": normalized_name,
                    "payload": _payload_from_asset(source_map.get(normalized_name)),
                }
            )
    return candidates


async def sync_from_extraction_draft(
    db: AsyncSession,
    *,
    chapter_id: str,
    draft: StudioScriptExtractionDraft,
) -> None:
    """将 chapter 级提取结果同步到各镜头候选项表。"""
    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        raise ValueError(entity_not_found("Chapter"))

    stmt = select(Shot).where(Shot.chapter_id == chapter_id)
    shots = (await db.execute(stmt)).scalars().all()
    shot_by_index = {shot.index: shot for shot in shots}
    character_by_name = {str(item.name).strip(): item for item in (draft.characters or []) if str(item.name).strip()}
    scene_by_name = {str(item.name).strip(): item for item in (draft.scenes or []) if str(item.name).strip()}
    prop_by_name = {str(item.name).strip(): item for item in (draft.props or []) if str(item.name).strip()}
    costume_by_name = {str(item.name).strip(): item for item in (draft.costumes or []) if str(item.name).strip()}

    for shot_draft in draft.shots:
        shot = shot_by_index.get(shot_draft.index)
        if shot is None:
            continue
        await replace_for_shot(
            db,
            shot_id=shot.id,
            candidates=_build_candidates_from_shot_draft(
                shot_draft,
                character_by_name=character_by_name,
                scene_by_name=scene_by_name,
                prop_by_name=prop_by_name,
                costume_by_name=costume_by_name,
            ),
        )


def sync_from_extraction_draft_sync(
    db: Session,
    *,
    chapter_id: str,
    draft: StudioScriptExtractionDraft,
) -> None:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise ValueError(entity_not_found("Chapter"))

    stmt = select(Shot).where(Shot.chapter_id == chapter_id)
    shots = db.execute(stmt).scalars().all()
    shot_by_index = {shot.index: shot for shot in shots}
    character_by_name = {str(item.name).strip(): item for item in (draft.characters or []) if str(item.name).strip()}
    scene_by_name = {str(item.name).strip(): item for item in (draft.scenes or []) if str(item.name).strip()}
    prop_by_name = {str(item.name).strip(): item for item in (draft.props or []) if str(item.name).strip()}
    costume_by_name = {str(item.name).strip(): item for item in (draft.costumes or []) if str(item.name).strip()}

    for shot_draft in draft.shots:
        shot = shot_by_index.get(shot_draft.index)
        if shot is None:
            continue
        replace_for_shot_sync(
            db,
            shot_id=shot.id,
            candidates=_build_candidates_from_shot_draft(
                shot_draft,
                character_by_name=character_by_name,
                scene_by_name=scene_by_name,
                prop_by_name=prop_by_name,
                costume_by_name=costume_by_name,
            ),
        )


async def replace_for_shot(
    db: AsyncSession,
    *,
    shot_id: str,
    candidates: list[dict[str, Any]],
) -> list[ShotExtractedCandidate]:
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise ValueError(entity_not_found("Shot"))

    existing_stmt = select(ShotExtractedCandidate).where(ShotExtractedCandidate.shot_id == shot_id)
    existing_rows = list((await db.execute(existing_stmt)).scalars().all())
    linked_by_key: dict[tuple[str, str], tuple[str | None, datetime | None]] = {}
    for row in existing_rows:
        if row.candidate_status != ShotCandidateStatus.linked:
            continue
        key = (str(row.candidate_type), str(row.candidate_name).strip())
        linked_by_key[key] = (row.linked_entity_id, row.confirmed_at)

    await db.execute(delete(ShotExtractedCandidate).where(ShotExtractedCandidate.shot_id == shot_id))
    shot.skip_extraction = False
    shot.last_extracted_at = _utc_now()

    rows: list[ShotExtractedCandidate] = []
    for item in candidates:
        candidate_type = ShotCandidateType(str(item["candidate_type"]))
        candidate_name = str(item["candidate_name"]).strip()
        linked_entity_id, confirmed_at = linked_by_key.get(
            (candidate_type.value, candidate_name),
            (None, None),
        )
        row = ShotExtractedCandidate(
            shot_id=shot_id,
            candidate_type=candidate_type,
            candidate_name=candidate_name,
            candidate_status=ShotCandidateStatus.linked if linked_entity_id else ShotCandidateStatus.pending,
            linked_entity_id=linked_entity_id,
            source=str(item.get("source") or "extraction"),
            payload=dict(item.get("payload") or {}),
            confirmed_at=confirmed_at,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    await recompute_shot_status(db, shot_id=shot_id)
    return rows


def replace_for_shot_sync(
    db: Session,
    *,
    shot_id: str,
    candidates: list[dict[str, Any]],
) -> list[ShotExtractedCandidate]:
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise ValueError(entity_not_found("Shot"))

    existing_stmt = select(ShotExtractedCandidate).where(ShotExtractedCandidate.shot_id == shot_id)
    existing_rows = list(db.execute(existing_stmt).scalars().all())
    linked_by_key: dict[tuple[str, str], tuple[str | None, datetime | None]] = {}
    for row in existing_rows:
        if row.candidate_status != ShotCandidateStatus.linked:
            continue
        key = (str(row.candidate_type), str(row.candidate_name).strip())
        linked_by_key[key] = (row.linked_entity_id, row.confirmed_at)

    db.execute(delete(ShotExtractedCandidate).where(ShotExtractedCandidate.shot_id == shot_id))
    shot.skip_extraction = False
    shot.last_extracted_at = _utc_now()

    rows: list[ShotExtractedCandidate] = []
    for item in candidates:
        candidate_type = ShotCandidateType(str(item["candidate_type"]))
        candidate_name = str(item["candidate_name"]).strip()
        linked_entity_id, confirmed_at = linked_by_key.get(
            (candidate_type.value, candidate_name),
            (None, None),
        )
        row = ShotExtractedCandidate(
            shot_id=shot_id,
            candidate_type=candidate_type,
            candidate_name=candidate_name,
            candidate_status=ShotCandidateStatus.linked if linked_entity_id else ShotCandidateStatus.pending,
            linked_entity_id=linked_entity_id,
            source=str(item.get("source") or "extraction"),
            payload=dict(item.get("payload") or {}),
            confirmed_at=confirmed_at,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    recompute_shot_status_sync(db, shot_id=shot_id)
    return rows


async def mark_linked(
    db: AsyncSession,
    *,
    candidate_id: int,
    linked_entity_id: str,
) -> ShotExtractedCandidate:
    row = await db.get(ShotExtractedCandidate, candidate_id)
    if row is None:
        raise ValueError(entity_not_found("ShotExtractedCandidate"))
    row.candidate_status = ShotCandidateStatus.linked
    row.linked_entity_id = linked_entity_id
    row.confirmed_at = _utc_now()
    await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=row.shot_id)
    return row


async def mark_linked_by_name(
    db: AsyncSession,
    *,
    shot_id: str,
    candidate_type: ShotCandidateType | str,
    candidate_name: str,
    linked_entity_id: str,
) -> ShotExtractedCandidate | None:
    """按镜头、候选类型与名称匹配候选项，并标记为已关联。

    用于真实资产关联动作发生后，将提取候选同步回写为 linked。
    若当前镜头没有匹配候选，则静默返回 None。

    说明：
        同一镜头内可能因重复提取出现多行同名同类候选，它们指向的是同一个真实实体，
        因此这里更新**全部**匹配行（D-8）；只更新第一条会让其余候选永远停在
        pending，把镜头状态卡在未确认。返回值保持既有契约：返回 ID 最小的匹配行。
    """
    normalized_name = str(candidate_name).strip()
    if not normalized_name:
        return None
    normalized_type = ShotCandidateType(str(candidate_type))
    stmt = (
        select(ShotExtractedCandidate)
        .where(ShotExtractedCandidate.shot_id == shot_id)
        .where(ShotExtractedCandidate.candidate_type == normalized_type)
        .where(ShotExtractedCandidate.candidate_name == normalized_name)
        .order_by(ShotExtractedCandidate.id.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return None
    for row in rows:
        row.candidate_status = ShotCandidateStatus.linked
        row.linked_entity_id = linked_entity_id
        row.confirmed_at = _utc_now()
    for row in rows:
        await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=rows[0].shot_id)
    return rows[0]


async def mark_pending_by_name(
    db: AsyncSession,
    *,
    shot_id: str,
    candidate_type: ShotCandidateType | str,
    candidate_name: str,
) -> ShotExtractedCandidate | None:
    """按镜头、候选类型与名称回退候选为待处理状态。

    说明：
        与 :func:`mark_linked_by_name` 对称，回退**全部**同名同类候选；
        否则「关联时全部置 linked、解除时只回退一条」会让剩余候选卡在 linked，
        镜头状态再也回不到 pending。返回值保持既有契约：返回 ID 最小的匹配行。
    """
    normalized_name = str(candidate_name).strip()
    if not normalized_name:
        return None
    normalized_type = ShotCandidateType(str(candidate_type))
    stmt = (
        select(ShotExtractedCandidate)
        .where(ShotExtractedCandidate.shot_id == shot_id)
        .where(ShotExtractedCandidate.candidate_type == normalized_type)
        .where(ShotExtractedCandidate.candidate_name == normalized_name)
        .order_by(ShotExtractedCandidate.id.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return None
    for row in rows:
        row.candidate_status = ShotCandidateStatus.pending
        row.linked_entity_id = None
        row.confirmed_at = None
    for row in rows:
        await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=rows[0].shot_id)
    return rows[0]


async def mark_pending_by_linked_entity(
    db: AsyncSession,
    *,
    shot_id: str,
    candidate_type: ShotCandidateType | str,
    linked_entity_id: str,
) -> ShotExtractedCandidate | None:
    """按镜头、候选类型与已关联实体 ID 回退候选为待处理状态。

    说明：
        一个实体可能被同一镜头的多行候选共同关联，因此这里回退**全部**匹配行，
        避免解除关联后仍有候选停在 linked。返回值保持既有契约：返回 ID 最小的匹配行。
    """
    normalized_type = ShotCandidateType(str(candidate_type))
    stmt = (
        select(ShotExtractedCandidate)
        .where(ShotExtractedCandidate.shot_id == shot_id)
        .where(ShotExtractedCandidate.candidate_type == normalized_type)
        .where(ShotExtractedCandidate.linked_entity_id == linked_entity_id)
        .order_by(ShotExtractedCandidate.id.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return None
    for row in rows:
        row.candidate_status = ShotCandidateStatus.pending
        row.linked_entity_id = None
        row.confirmed_at = None
    for row in rows:
        await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=rows[0].shot_id)
    return rows[0]


async def mark_ignored(
    db: AsyncSession,
    *,
    candidate_id: int,
) -> ShotExtractedCandidate:
    row = await db.get(ShotExtractedCandidate, candidate_id)
    if row is None:
        raise ValueError(entity_not_found("ShotExtractedCandidate"))
    row.candidate_status = ShotCandidateStatus.ignored
    row.linked_entity_id = None
    row.confirmed_at = _utc_now()
    await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=row.shot_id)
    return row


async def set_skip_extraction(
    db: AsyncSession,
    *,
    shot_id: str,
    skip: bool,
) -> Shot:
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise ValueError(entity_not_found("Shot"))
    shot.skip_extraction = skip
    if skip:
        shot.last_extracted_at = _utc_now()
    await db.flush()
    await recompute_shot_status(db, shot_id=shot_id)
    return shot
