"""镜头对白提取候选项服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.studio import (
    Chapter,
    Character,
    DialogueLineMode,
    Shot,
    ShotDetail,
    ShotDialogLine,
    ShotDialogueCandidateStatus,
    ShotExtractedDialogueCandidate,
)
from app.schemas.skills.script_processing import StudioScriptExtractionDraft
from app.schemas.studio.shots import ShotExtractedDialogueCandidateAcceptRequest
from app.services.common import entity_not_found
from app.services.studio.shot_status import recompute_shot_status, recompute_shot_status_sync


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _flush_refresh_candidate(
    db: AsyncSession,
    row: ShotExtractedDialogueCandidate,
) -> ShotExtractedDialogueCandidate:
    """刷新 candidate，避免响应序列化时触发异步懒加载。"""
    await db.flush()
    await db.refresh(row)
    return row


async def list_by_shot(
    db: AsyncSession,
    *,
    shot_id: str,
) -> list[ShotExtractedDialogueCandidate]:
    stmt = (
        select(ShotExtractedDialogueCandidate)
        .where(ShotExtractedDialogueCandidate.shot_id == shot_id)
        .order_by(ShotExtractedDialogueCandidate.index.asc(), ShotExtractedDialogueCandidate.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


def _dialogue_line_mode(value: Any) -> DialogueLineMode:
    if isinstance(value, DialogueLineMode):
        return value
    return DialogueLineMode(str(value or DialogueLineMode.dialogue.value))


def _clean_emotion(value: Any) -> str | None:
    """情绪/语气归一化（提示词改造第 2 档 F 项）。

    LLM 可能给出 None / 空串 / 纯空白；数据库列是 varchar(64)，超长要在这里截断，
    否则严格模式下 MySQL 会直接报错，把整条提取结果打回。
    """
    text = str(value or "").strip()
    if not text:
        return None
    return text[:64]


def _build_candidates_from_shot_draft(shot_draft: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in list(getattr(shot_draft, "dialogue_lines", []) or []):
        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue
        candidates.append(
            {
                "index": int(getattr(item, "index", 0) or 0),
                "text": text,
                "line_mode": _dialogue_line_mode(getattr(item, "line_mode", DialogueLineMode.dialogue)),
                "emotion": _clean_emotion(getattr(item, "emotion", None)),
                "speaker_name": getattr(item, "speaker_name", None),
                "target_name": getattr(item, "target_name", None),
                "payload": {},
            }
        )
    return candidates


async def sync_from_extraction_draft(
    db: AsyncSession,
    *,
    chapter_id: str,
    draft: StudioScriptExtractionDraft,
) -> None:
    """将 chapter 级提取结果同步到各镜头对白候选项表。"""
    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        raise ValueError(entity_not_found("Chapter"))

    stmt = select(Shot).where(Shot.chapter_id == chapter_id)
    shots = (await db.execute(stmt)).scalars().all()
    shot_by_index = {shot.index: shot for shot in shots}

    for shot_draft in draft.shots:
        shot = shot_by_index.get(shot_draft.index)
        if shot is None:
            continue
        await replace_for_shot(
            db,
            shot_id=shot.id,
            candidates=_build_candidates_from_shot_draft(shot_draft),
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

    for shot_draft in draft.shots:
        shot = shot_by_index.get(shot_draft.index)
        if shot is None:
            continue
        replace_for_shot_sync(
            db,
            shot_id=shot.id,
            candidates=_build_candidates_from_shot_draft(shot_draft),
        )


async def replace_for_shot(
    db: AsyncSession,
    *,
    shot_id: str,
    candidates: list[dict[str, Any]],
) -> list[ShotExtractedDialogueCandidate]:
    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise ValueError(entity_not_found("Shot"))

    existing_stmt = select(ShotExtractedDialogueCandidate).where(
        ShotExtractedDialogueCandidate.shot_id == shot_id
    )
    existing_rows = list((await db.execute(existing_stmt)).scalars().all())
    accepted_by_key: dict[tuple[str, str, str], tuple[int | None, datetime | None]] = {}
    for row in existing_rows:
        if row.candidate_status != ShotDialogueCandidateStatus.accepted:
            continue
        key = (
            str(row.text).strip(),
            str(row.speaker_name or "").strip(),
            str(row.target_name or "").strip(),
        )
        accepted_by_key[key] = (row.linked_dialog_line_id, row.confirmed_at)

    await db.execute(
        delete(ShotExtractedDialogueCandidate).where(ShotExtractedDialogueCandidate.shot_id == shot_id)
    )
    shot.skip_extraction = False
    shot.last_extracted_at = _utc_now()

    rows: list[ShotExtractedDialogueCandidate] = []
    for item in candidates:
        text = str(item["text"]).strip()
        speaker_name = item.get("speaker_name")
        target_name = item.get("target_name")
        key = (text, str(speaker_name or "").strip(), str(target_name or "").strip())
        linked_dialog_line_id, confirmed_at = accepted_by_key.get(key, (None, None))
        row = ShotExtractedDialogueCandidate(
            shot_id=shot_id,
            index=int(item.get("index") or 0),
            text=text,
            line_mode=_dialogue_line_mode(item.get("line_mode")),
            emotion=_clean_emotion(item.get("emotion")),
            speaker_name=speaker_name,
            target_name=target_name,
            candidate_status=(
                ShotDialogueCandidateStatus.accepted
                if linked_dialog_line_id
                else ShotDialogueCandidateStatus.pending
            ),
            linked_dialog_line_id=linked_dialog_line_id,
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
) -> list[ShotExtractedDialogueCandidate]:
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise ValueError(entity_not_found("Shot"))

    existing_stmt = select(ShotExtractedDialogueCandidate).where(
        ShotExtractedDialogueCandidate.shot_id == shot_id
    )
    existing_rows = list(db.execute(existing_stmt).scalars().all())
    accepted_by_key: dict[tuple[str, str, str], tuple[int | None, datetime | None]] = {}
    for row in existing_rows:
        if row.candidate_status != ShotDialogueCandidateStatus.accepted:
            continue
        key = (
            str(row.text).strip(),
            str(row.speaker_name or "").strip(),
            str(row.target_name or "").strip(),
        )
        accepted_by_key[key] = (row.linked_dialog_line_id, row.confirmed_at)

    db.execute(
        delete(ShotExtractedDialogueCandidate).where(ShotExtractedDialogueCandidate.shot_id == shot_id)
    )
    shot.skip_extraction = False
    shot.last_extracted_at = _utc_now()

    rows: list[ShotExtractedDialogueCandidate] = []
    for item in candidates:
        text = str(item["text"]).strip()
        speaker_name = item.get("speaker_name")
        target_name = item.get("target_name")
        key = (text, str(speaker_name or "").strip(), str(target_name or "").strip())
        linked_dialog_line_id, confirmed_at = accepted_by_key.get(key, (None, None))
        row = ShotExtractedDialogueCandidate(
            shot_id=shot_id,
            index=int(item.get("index") or 0),
            text=text,
            line_mode=_dialogue_line_mode(item.get("line_mode")),
            emotion=_clean_emotion(item.get("emotion")),
            speaker_name=speaker_name,
            target_name=target_name,
            candidate_status=(
                ShotDialogueCandidateStatus.accepted
                if linked_dialog_line_id
                else ShotDialogueCandidateStatus.pending
            ),
            linked_dialog_line_id=linked_dialog_line_id,
            source=str(item.get("source") or "extraction"),
            payload=dict(item.get("payload") or {}),
            confirmed_at=confirmed_at,
        )
        db.add(row)
        rows.append(row)

    db.flush()
    recompute_shot_status_sync(db, shot_id=shot_id)
    return rows


async def _resolve_dialog_index(db: AsyncSession, *, shot_id: str, preferred_index: int) -> int:
    existing_stmt = select(ShotDialogLine.id).where(
        ShotDialogLine.shot_detail_id == shot_id,
        ShotDialogLine.index == preferred_index,
    )
    existing = (await db.execute(existing_stmt)).first()
    if existing is None:
        return preferred_index
    max_index = await db.scalar(
        select(func.max(ShotDialogLine.index)).where(ShotDialogLine.shot_detail_id == shot_id)
    )
    return int(max_index or 0) + 1


async def _resolve_character_id_by_name(
    db: AsyncSession,
    *,
    shot_id: str,
    character_name: str | None,
) -> str | None:
    """按角色名解析镜头所属项目内的角色 ID。

    对白候选只保存了角色名，接受动作必须把 ``speaker_character_id`` /
    ``target_character_id`` 一并写入台词行：否则展示层没有可解析的角色关联，
    角色改名后台词行会一直显示旧的提取名字（B-2）。

    参数：
        shot_id：候选所属镜头 ID，用于反查项目范围。
        character_name：候选（或接受请求覆盖后）的角色名。

    返回：
        命中的角色 ID；名字为空、镜头/章节缺失或项目内无同名角色时返回 ``None``，
        此时展示层回落到行内名字。

    说明：
        只在同一项目内匹配，避免不同项目的同名角色被误关联；项目内存在同名角色时
        取 ID 最小者，保证结果稳定可复现。
    """
    normalized_name = str(character_name or "").strip()
    if not normalized_name:
        return None
    shot = await db.get(Shot, shot_id)
    if shot is None:
        return None
    chapter = await db.get(Chapter, shot.chapter_id)
    if chapter is None:
        return None
    stmt = (
        select(Character.id)
        .where(Character.project_id == chapter.project_id)
        .where(Character.name == normalized_name)
        .order_by(Character.id.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def mark_accepted(
    db: AsyncSession,
    *,
    candidate_id: int,
    body: ShotExtractedDialogueCandidateAcceptRequest | None = None,
) -> ShotExtractedDialogueCandidate:
    row = await db.get(ShotExtractedDialogueCandidate, candidate_id)
    if row is None:
        raise ValueError(entity_not_found("ShotExtractedDialogueCandidate"))

    detail = await db.get(ShotDetail, row.shot_id)
    if detail is None:
        raise ValueError(entity_not_found("ShotDetail"))

    body = body or ShotExtractedDialogueCandidateAcceptRequest()
    line_index = await _resolve_dialog_index(
        db,
        shot_id=row.shot_id,
        preferred_index=row.index if body.index is None else body.index,
    )
    speaker_name = body.speaker_name if body.speaker_name is not None else row.speaker_name
    target_name = body.target_name if body.target_name is not None else row.target_name
    line = ShotDialogLine(
        shot_detail_id=row.shot_id,
        index=line_index,
        text=(body.text if body.text is not None else row.text),
        line_mode=(body.line_mode if body.line_mode is not None else row.line_mode),
        emotion=(
            _clean_emotion(body.emotion)
            if body.emotion is not None
            else _clean_emotion(row.emotion)
        ),
        speaker_character_id=await _resolve_character_id_by_name(
            db, shot_id=row.shot_id, character_name=speaker_name
        ),
        target_character_id=await _resolve_character_id_by_name(
            db, shot_id=row.shot_id, character_name=target_name
        ),
        speaker_name=speaker_name,
        target_name=target_name,
    )
    db.add(line)
    await db.flush()
    await db.refresh(line)

    row.candidate_status = ShotDialogueCandidateStatus.accepted
    row.linked_dialog_line_id = line.id
    row.confirmed_at = _utc_now()
    await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=row.shot_id)
    return row


async def mark_ignored(
    db: AsyncSession,
    *,
    candidate_id: int,
) -> ShotExtractedDialogueCandidate:
    row = await db.get(ShotExtractedDialogueCandidate, candidate_id)
    if row is None:
        raise ValueError(entity_not_found("ShotExtractedDialogueCandidate"))
    row.candidate_status = ShotDialogueCandidateStatus.ignored
    row.linked_dialog_line_id = None
    row.confirmed_at = _utc_now()
    await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=row.shot_id)
    return row


async def mark_pending_by_linked_dialog_line(
    db: AsyncSession,
    *,
    dialog_line_id: int,
) -> ShotExtractedDialogueCandidate | None:
    """当已接受的对白被删除后，将对应 candidate 回退到 pending。"""
    stmt = (
        select(ShotExtractedDialogueCandidate)
        .where(ShotExtractedDialogueCandidate.linked_dialog_line_id == dialog_line_id)
        .limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        return None
    row.candidate_status = ShotDialogueCandidateStatus.pending
    row.linked_dialog_line_id = None
    row.confirmed_at = None
    await _flush_refresh_candidate(db, row)
    await recompute_shot_status(db, shot_id=row.shot_id)
    return row
