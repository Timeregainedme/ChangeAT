from __future__ import annotations

from app.models.studio import ShotFrameType
from app.schemas.studio.shots import ShotFramePromptMappingRead, ShotLinkedAssetItem
from app.services.studio.generation.shared.types import GenerationContext

# C3：参考图任务强制让「角色卡」排在最前面（即 图1），锁住人物身份。
# 排序与 IR 层（`app/chains/prompts/ir.py` 的 `_collect_asset_references`）保持一致：
# 角色 → 场景 → 道具 → 服装，同类内保持调用方给定顺序（稳定排序）。
# 只有顺序由服务端决定才安全：`derive_preview` 会据此重建 token 列表，并把提示词里的
# 实体名替换成 token，因此客户端不需要、也不应该自己编号。
_REFERENCE_KIND_PRIORITY: dict[str, int] = {
    "character": 0,
    "scene": 1,
    "prop": 2,
    "costume": 3,
}


def _reference_priority(item: ShotLinkedAssetItem) -> int:
    return _REFERENCE_KIND_PRIORITY.get(str(getattr(item, "type", "") or "").strip().lower(), 99)


def build_ordered_shot_frame_references(
    *,
    items: list[ShotLinkedAssetItem],
) -> list[ShotFramePromptMappingRead]:
    """构造稳定的图片映射关系：角色卡优先作 图1，其后按 场景 → 道具 → 服装。

    同类内保持调用方给定顺序（`sorted` 稳定）。未识别的类别排在最后，不丢弃。
    """
    mappings: list[ShotFramePromptMappingRead] = []
    seen_file_ids: set[str] = set()
    ordered_items = sorted(list(items or []), key=_reference_priority)
    for item in ordered_items:
        file_id = (item.file_id or "").strip()
        if not file_id or file_id in seen_file_ids:
            continue
        seen_file_ids.add(file_id)
        mappings.append(
            ShotFramePromptMappingRead(
                token=f"图{len(mappings) + 1}",
                type=item.type,
                id=item.id,
                name=(item.name or "").strip() or item.id,
                file_id=file_id,
            )
        )
    return mappings


class FrameGenerationContext(GenerationContext):
    """分镜帧图片生成的动态上下文。"""

    kind: str = "frame"
    shot_id: str
    frame_type: ShotFrameType
    images: list[ShotLinkedAssetItem]
    ordered_refs: list[ShotFramePromptMappingRead]


def build_frame_context(
    *,
    shot_id: str,
    frame_type: ShotFrameType,
    items: list[ShotLinkedAssetItem],
) -> FrameGenerationContext:
    return FrameGenerationContext(
        shot_id=shot_id,
        frame_type=frame_type,
        images=items or [],
        ordered_refs=build_ordered_shot_frame_references(items=items),
    )

