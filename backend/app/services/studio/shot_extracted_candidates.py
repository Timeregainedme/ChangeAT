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
    payload: dict[str, Any] = {}
    for key in ("id", "file_id", "thumbnail", "description", "voice_description"):
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
        .limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        return None
    row.candidate_status = ShotCandidateStatus.linked
    row.linked_entity_id = linked_entity_id
    row.confirmed_at = _utc_now()
    await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=row.shot_id)
    return row


async def mark_pending_by_name(
    db: AsyncSession,
    *,
    shot_id: str,
    candidate_type: ShotCandidateType | str,
    candidate_name: str,
) -> ShotExtractedCandidate | None:
    """按镜头、候选类型与名称回退候选为待处理状态。"""
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
        .limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        return None
    row.candidate_status = ShotCandidateStatus.pending
    row.linked_entity_id = None
    row.confirmed_at = None
    await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=row.shot_id)
    return row


async def mark_pending_by_linked_entity(
    db: AsyncSession,
    *,
    shot_id: str,
    candidate_type: ShotCandidateType | str,
    linked_entity_id: str,
) -> ShotExtractedCandidate | None:
    """按镜头、候选类型与已关联实体 ID 回退候选为待处理状态。"""
    normalized_type = ShotCandidateType(str(candidate_type))
    stmt = (
        select(ShotExtractedCandidate)
        .where(ShotExtractedCandidate.shot_id == shot_id)
        .where(ShotExtractedCandidate.candidate_type == normalized_type)
        .where(ShotExtractedCandidate.linked_entity_id == linked_entity_id)
        .order_by(ShotExtractedCandidate.id.asc())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        return None
    row.candidate_status = ShotCandidateStatus.pending
    row.linked_entity_id = None
    row.confirmed_at = None
    await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=row.shot_id)
    return row


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
