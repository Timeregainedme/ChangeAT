from __future__ import annotations

from pydantic import Field

from app.services.studio.generation.asset_image.build_base import AssetImageBaseDraft
from app.services.studio.generation.asset_image.build_context import AssetImageContext
from app.services.studio.generation.shared.types import GenerationDerivedPreview


class AssetImageDerivedPreview(GenerationDerivedPreview):
    """资产图片生成预览。"""

    kind: str = "asset_image"
    entity_type: str
    entity_id: str
    relation_type: str
    relation_entity_id: str
    prompt: str
    images: list[str]
    # 参考图缺失说明。必须逐层透传到响应体，否则前端只能看到「prompt + 若干图」，
    # 无法解释为什么本次生成一张参考图都没有（参考图缺失不得静默）。
    reference_warnings: list[str] = Field(default_factory=list)


def derive_asset_image_preview(
    *,
    base: AssetImageBaseDraft,
    context: AssetImageContext,
) -> AssetImageDerivedPreview:
    return AssetImageDerivedPreview(
        entity_type=base.entity_type,
        entity_id=base.entity_id,
        relation_type=base.relation_type,
        relation_entity_id=base.relation_entity_id,
        prompt=(base.prompt or "").strip(),
        images=context.images,
        reference_warnings=base.reference_warnings,
    )

