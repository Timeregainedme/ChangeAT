"""批量资产参考图生成服务。

为角色/场景/道具/服装「一键」批量创建图片生成任务：
- **必须指定 project_id**：只处理该项目下的资产，避免误扫全库；
- 对每个资产自动选取 front 优先的图片槽位（image_id），角色缺槽位时按需补齐；
- 复用资产图片的 base draft + derive preview 生成提示词与参考图；
- 两阶段提交：先 stage 全部任务行并一次性提交，再统一入队，避免中途失败留下
  「部分任务已入队」的半成品；单个资产的失败用 SAVEPOINT 隔离，不污染会话。

对应 ToonFlow 式工作流中的「提取完成后一键生成参考图」环节。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.image_generation import DEFAULT_IMAGE_OUTPUT_FORMAT
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.studio import (
    ActorImage,
    Character,
    CharacterImage,
    CostumeImage,
    Project,
    PropImage,
    SceneImage,
)
from app.models.types import AssetQualityLevel, AssetViewAngle
from app.services.common import entity_not_found
from app.services.studio.entity_specs import LINK_MODEL_BY_ENTITY
from app.services.studio.generation.asset_image import (
    build_actor_image_base_draft,
    build_asset_image_base_draft,
    build_asset_image_context,
    build_character_image_base_draft,
    derive_asset_image_preview,
)
from app.services.studio.image_task_runner import stage_image_task_and_link


logger = logging.getLogger(__name__)

# 批量支持的资产类型。
# 为什么含 actor：演员图是**角色图的前置参考图**（构建角色图时会先取该角色
# `actor_id` 的图片、再取 `costume_id` 的图片），用户需要能「一键把演员图全生出来」，
# 否则角色图会在零参考图的情况下静默生成。
BATCH_ASSET_TYPES = ("actor", "character", "scene", "prop", "costume")

# 单次批量的资产数量上限：防止误操作对全库资产提交无界生成任务（成本保护）。
MAX_BATCH_ASSETS = 200

# 各资产类型的图片表与其所属外键字段名（用于批量取槽位）。
_ASSET_IMAGE_MODEL_BY_TYPE: dict[str, Any] = {
    "actor": (ActorImage, "actor_id"),
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


async def _ensure_asset_image_slot(
    db: AsyncSession,
    *,
    asset_type: str,
    asset_id: str,
) -> int | None:
    """确保资产至少有一个图片槽位，返回新槽位 ID（无法补齐时返回 None）。

    角色经 create_entity 创建时不会预建图片槽位（actor/scene/prop/costume 会），
    因此这里按需补一个 front 空槽位；否则「一键批量参考图」对角色会全部跳过。
    """
    if asset_type != "character":
        return None
    slot = CharacterImage(
        character_id=asset_id,
        file_id=None,
        quality_level=AssetQualityLevel.low,
        view_angle=AssetViewAngle.front,
        format=DEFAULT_IMAGE_OUTPUT_FORMAT,
        is_primary=True,
    )
    db.add(slot)
    await db.flush()
    return int(slot.id)


async def _project_asset_ids(
    db: AsyncSession,
    *,
    asset_type: str,
    project_id: str,
) -> list[str]:
    """取项目下的资产 ID 列表（角色直挂 project_id，其余经项目关联表）。"""
    if asset_type == "character":
        stmt = select(Character.id).where(Character.project_id == project_id)
    else:
        link_model, asset_field = LINK_MODEL_BY_ENTITY[asset_type]
        stmt = select(getattr(link_model, asset_field)).where(link_model.project_id == project_id)
    return [str(x) for x in (await db.execute(stmt)).scalars().all() if x]


async def _create_single_asset_image_task(
    db: AsyncSession,
    *,
    asset_type: str,
    asset_id: str,
    image_id: int,
) -> tuple[str, str]:
    """为单个资产 stage 图片生成任务，返回 (task_id, prompt)。不提交、不入队。"""
    if asset_type == "character":
        base = await build_character_image_base_draft(
            db,
            character_id=asset_id,
            image_id=image_id,
        )
    elif asset_type == "actor":
        # 演员走独立入口：其图片表与校验函数与 scene/prop/costume 不同源
        # （见 build_actor_image_base_draft / validate_actor_image）。
        base = await build_actor_image_base_draft(
            db,
            actor_id=asset_id,
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
    task_id = await stage_image_task_and_link(
        db=db,
        model_id=None,
        relation_type=derived.relation_type,
        relation_entity_id=derived.relation_entity_id,
        prompt=derived.prompt,
        images=derived.images,
    )
    return task_id, derived.prompt


def _enqueue(task_id: str) -> None:
    """把任务交给 Celery 执行（延迟导入避免模块级循环依赖；测试可替换）。"""
    from app.tasks.execute_task import enqueue_task_execution

    enqueue_task_execution(task_id)


async def create_batch_asset_image_tasks(
    db: AsyncSession,
    *,
    asset_type: str,
    project_id: str,
    asset_ids: list[str] | None = None,
    max_assets: int = MAX_BATCH_ASSETS,
) -> dict[str, Any]:
    """批量创建资产图片生成任务（限定在单个项目内）。

    返回 ``{"tasks": [...], "skipped": [...], "enqueue_failed": [...]}``：
    ``tasks`` 只包含**已成功入队**的任务；无图片槽位或 stage 失败的资产记入
    ``skipped``；已提交但入队失败的任务记入 ``enqueue_failed``（该任务行会被
    标记为 failed，不会永久停在 pending）。以上三类均不阻断其余资产；
    超出 max_assets 直接报错，避免无界提交生成任务。
    """
    asset_type_norm = asset_type.strip().lower()
    if asset_type_norm not in BATCH_ASSET_TYPES:
        raise ValueError(f"unsupported asset_type: {asset_type}")

    if await db.get(Project, project_id) is None:
        raise ValueError(entity_not_found("Project"))

    project_ids = set(
        await _project_asset_ids(db, asset_type=asset_type_norm, project_id=project_id)
    )

    skipped: list[dict[str, str]] = []
    if asset_ids:
        requested = list(dict.fromkeys(str(x).strip() for x in asset_ids if str(x).strip()))
        targets = [x for x in requested if x in project_ids]
        skipped.extend(
            {"asset_id": x, "reason": "not in project"} for x in requested if x not in project_ids
        )
    else:
        targets = sorted(project_ids)

    if len(targets) > max_assets:
        raise ValueError(
            f"too many assets: {len(targets)} > {max_assets}；请缩小 asset_ids 范围或分批执行"
        )

    staged: list[tuple[str, str, str]] = []
    for asset_id in targets:
        image_id = await pick_primary_image_id(db, asset_type=asset_type_norm, asset_id=asset_id)
        if image_id is None:
            image_id = await _ensure_asset_image_slot(
                db, asset_type=asset_type_norm, asset_id=asset_id
            )
        if image_id is None:
            skipped.append({"asset_id": asset_id, "reason": "no image slot"})
            continue
        try:
            async with db.begin_nested():
                task_id, prompt = await _create_single_asset_image_task(
                    db,
                    asset_type=asset_type_norm,
                    asset_id=asset_id,
                    image_id=image_id,
                )
        except Exception as exc:  # noqa: BLE001 - 单个资产失败不应阻断批量
            skipped.append({"asset_id": asset_id, "reason": str(exc)})
            continue
        staged.append((asset_id, task_id, prompt))

    tasks: list[dict[str, Any]] = []
    enqueue_failed: list[dict[str, str]] = []
    if staged:
        await db.commit()

        for asset_id, task_id, prompt in staged:
            try:
                _enqueue(task_id)
            except Exception as exc:  # noqa: BLE001 - 单个任务入队失败不应阻断其余任务
                # 任务行已 commit，若不显式标记失败会永久停在 pending（与单资产路径同源）。
                logger.exception("failed to enqueue batch asset image task: task_id=%s", task_id)
                fail_store = SqlAlchemyTaskStore(db)
                await fail_store.set_status(task_id, TaskStatus.failed)
                await fail_store.set_error(task_id, f"enqueue failed: {exc}")
                await db.commit()
                enqueue_failed.append(
                    {"asset_id": asset_id, "task_id": task_id, "reason": str(exc)}
                )
                continue
            tasks.append({"asset_id": asset_id, "task_id": task_id, "prompt": prompt})

    return {"tasks": tasks, "skipped": skipped, "enqueue_failed": enqueue_failed}
