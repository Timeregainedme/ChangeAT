from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import AssetViewAngle
from app.schemas.studio.shots import ShotLinkedAssetItem
from app.services.media_reference_files import compact_image_reference_refs


async def resolve_reference_file_ids_and_names_from_linked_items(
    db: AsyncSession,  # noqa: ARG001
    *,
    items: list[ShotLinkedAssetItem],
) -> tuple[list[str], list[str]]:
    """将关联资产条目解析为参考图 file_id 列表（顺序有效）。"""
    file_ids: list[str] = []
    names: list[str] = []
    for item in items or []:
        name = (item.name or "").strip()
        file_id = (item.file_id or "").strip()
        if not file_id:
            continue
        file_ids.append(str(file_id))
        names.append(name or (item.id or ""))
    return file_ids, names


async def compact_reference_image_refs_by_file_ids(
    db: AsyncSession,
    *,
    file_ids: list[str],
) -> list[dict[str, str]]:
    """将 file_id 列表校验为**紧凑引用** ``[{"file_id": ...}]``，顺序与入参一致。

    只校验、只留 id：字节内容推迟到任务执行端物化（见
    `app.services.media_reference_files.materialize_image_reference_refs`），
    避免把 base64 写进 `generation_tasks.payload`。
    """
    return await compact_image_reference_refs(db, file_ids=file_ids)


async def pick_front_ref_file_id(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_id: str,
    preferred_quality_level: object | None,
) -> str | None:
    """按旧语义挑选 front 参考图的 file_id（不下载文件）。"""
    parent_field = getattr(image_model, parent_field_name)
    stmt = (
        select(image_model)
        .where(
            parent_field == parent_id,
            image_model.view_angle == AssetViewAngle.front,
            image_model.file_id.is_not(None),
        )
        .order_by(image_model.created_at.desc(), image_model.id.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return None

    target = rows[0]
    if preferred_quality_level is not None:
        for row in rows:
            if getattr(row, "quality_level", None) == preferred_quality_level:
                target = row
                break

    fid = getattr(target, "file_id", None)
    return str(fid) if fid else None


async def pick_ordered_ref_file_ids(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_id: str,
    view_angles: tuple[AssetViewAngle, ...],
) -> list[str]:
    """按旧语义按角度顺序挑选参考图 file_id（不下载文件）。"""
    parent_field = getattr(image_model, parent_field_name)
    stmt = (
        select(image_model)
        .where(parent_field == parent_id, image_model.file_id.is_not(None))
        .order_by(image_model.created_at.desc(), image_model.id.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    best_by_angle: dict[str, object] = {}
    for row in rows:
        angle = getattr(row, "view_angle", None)
        key = angle.value if isinstance(angle, AssetViewAngle) else str(angle)
        if key and key not in best_by_angle:
            best_by_angle[key] = row

    out: list[str] = []
    for angle in view_angles:
        row = best_by_angle.get(angle.value)
        if row is None:
            continue
        fid = getattr(row, "file_id", None)
        if fid:
            out.append(str(fid))
    return out
