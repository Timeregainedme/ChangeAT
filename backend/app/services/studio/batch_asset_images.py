"""批量资产参考图生成服务。

为角色/场景/道具/服装「一键」批量创建图片生成任务：
- 对每个资产自动选取 front 优先的图片槽位（image_id），避免调用方手动指定；
- 复用资产图片的 base draft + derive preview 生成提示词；
- 通过 create_image_task_and_link 创建任务并挂载到对应资产。

对应 ToonFlow 式工作流中的「提取完成后一键生成参考图」环节。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import (
    CharacterImage,
    CostumeImage,
    PropImage,
    SceneImage,
)
from app.models.types import AssetViewAngle
from app.services.studio.generation.asset_image import (
    build_asset_image_base_draft,
    build_asset_image_context,
    build_character_image_base_draft,
    derive_asset_image_preview,
)
from app.services.studio.image_task_runner import create_image_task_and_link


BATCH_ASSET_TYPES = ("character", "scene", "prop", "costume")

# 各资产类型的图片表与其所属外键字段名（用于批量取槽位）。
_ASSET_IMAGE_MODEL_BY_TYPE: dict[str, Any] = {
    "character": (CharacterImage, "character_id"),
    "scene": (SceneImage, "scene_id"),
    "prop": (PropImage, "prop_id"),
    "costume": (CostumeImage, "costume_id"),
}


async def pick_primary_image_id(
    db: AsyncSession,
    *,
    asset_type: str,
    asset_id: str,
) -> int | None:
    """取资产下 front 优先的第一张图片槽位 ID（无图返回 None）。"""
    image_model, parent_field = _ASSET_IMAGE_MODEL_BY_TYPE[asset_type]
    order_terms: list[Any] = [(getattr(image_model, "view_angle") == AssetViewAngle.front).desc()]
    if hasattr(image_model, "is_primary"):
        order_terms.append(getattr(image_model, "is_primary").desc())
    order_terms.append(getattr(image_model, "id").asc())
    stmt = (
        select(image_model.id)
        .where(getattr(image_model, parent_field) == asset_id)
        .order_by(*order_terms)
        .limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()
    return int(row) if row is not None else None


async def _create_single_asset_image_task(
    db: AsyncSession,
    *,
    asset_type: str,
    asset_id: str,
    image_id: int,
) -> tuple[str, str]:
    """为单个资产创建图片生成任务，返回 (task_id, prompt)。"""
    if asset_type == "character":
        base = await build_character_image_base_draft(
            db,
            character_id=asset_id,
            image_id=image_id,
        )
    else:
        base = await build_asset_image_base_draft(
            db,
            asset_type=asset_type,
            asset_id=asset_id,
            image_id=image_id,
        )
    context = build_asset_image_context(base=base)
    derived = derive_asset_image_preview(base=base, context=context)
    task_id = await create_image_task_and_link(
        db=db,
        model_id=None,
        relation_type=derived.relation_type,
        relation_entity_id=derived.relation_entity_id,
        prompt=derived.prompt,
        images=None,
    )
    return task_id, derived.prompt


async def create_batch_asset_image_tasks(
    db: AsyncSession,
    *,
    asset_type: str,
    asset_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """批量创建资产图片生成任务。

    返回按调用顺序排列的 [{"asset_id", "task_id", "prompt"}]；无图片槽位或
    生成失败的资产记入 skipped 列表（不阻断其余资产）。
    """
    asset_type_norm = asset_type.strip().lower()
    if asset_type_norm not in BATCH_ASSET_TYPES:
        raise ValueError(f"unsupported asset_type: {asset_type}")

    image_model, parent_field = _ASSET_IMAGE_MODEL_BY_TYPE[asset_type_norm]

    if asset_ids:
        targets = list(dict.fromkeys(str(x).strip() for x in asset_ids if str(x).strip()))
    else:
        stmt = select(getattr(image_model, parent_field)).distinct()
        targets = [str(x) for x in (await db.execute(stmt)).scalars().all() if x]

    tasks: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for asset_id in targets:
        image_id = await pick_primary_image_id(db, asset_type=asset_type_norm, asset_id=asset_id)
        if image_id is None:
            skipped.append({"asset_id": asset_id, "reason": "no image slot"})
            continue
        try:
            task_id, prompt = await _create_single_asset_image_task(
                db,
                asset_type=asset_type_norm,
                asset_id=asset_id,
                image_id=image_id,
            )
        except Exception as exc:  # noqa: BLE001 - 单个资产失败不应阻断批量
            skipped.append({"asset_id": asset_id, "reason": str(exc)})
            continue
        tasks.append({"asset_id": asset_id, "task_id": task_id, "prompt": prompt})

    return [{"tasks": tasks, "skipped": skipped}]
