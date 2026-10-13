"""PIX 图片能力声明与覆盖注册。

PIX 的图片接口用「分辨率档位」而非像素尺寸：`1K` / `2K` / `4K`。
因此这里把 `ratio_size_profiles` 映射为档位字符串，
使 `resolve_image_size(purpose="video_reference")` 推导出的 size 可直接透传。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.integrations.image_capabilities import (
    ImageCapabilityProvider,
    ImageModelCapability,
    register_image_capability_provider,
)
from app.core.integrations.provider_capabilities import PrefixCapabilityStore

if TYPE_CHECKING:
    from app.core.contracts.image_generation import ImageGenerationInput

# PIX 支持的画幅与 Jellyfish 的 ImageTargetRatio 字面量取交集后的结果。
PIX_IMAGE_RATIOS = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "3:2", "2:3"}
PIX_IMAGE_SIZES = {"1K", "2K", "4K"}

# 出图档位：standard → 1K，high → 2K（与 pix.ts 中默认 2K 的取向一致）。
_PIX_RATIO_SIZE_PROFILES = {
    ratio: {"standard": "1K", "high": "2K"} for ratio in sorted(PIX_IMAGE_RATIOS)
}

_PIX_DEFAULT = ImageModelCapability(
    # PIX 图片接口不接受 seed / watermark。
    supports_seed=False,
    supports_watermark=False,
    allowed_sizes=set(PIX_IMAGE_SIZES),
    supported_ratios=set(PIX_IMAGE_RATIOS),
    default_resolution_profile="standard",
    ratio_size_profiles=_PIX_RATIO_SIZE_PROFILES,
    # 一次任务只返回一个 output_url。
    min_n=1,
    max_n=1,
)

_STORE: PrefixCapabilityStore[ImageModelCapability] = PrefixCapabilityStore(
    provider="pix",
    default=_PIX_DEFAULT,
)


def register_pix_image_capability(*, model_prefix: str, capability: ImageModelCapability) -> None:
    _STORE.register(model_prefix=model_prefix, capability=capability)


def clear_pix_image_capability_overrides() -> None:
    _STORE.clear()


def resolve_pix_image_capability(model: str | None) -> ImageModelCapability:
    return _STORE.resolve(model)


def validate_pix_image_options(input_: ImageGenerationInput) -> None:
    """PIX 能力校验入口（避免调用侧传 provider 字面量）。"""
    from app.core.contracts.image_generation import ImageGenerationInput
    from app.core.integrations.image_capabilities import validate_image_options

    assert isinstance(input_, ImageGenerationInput)
    validate_image_options(provider="pix", model=input_.model, input_=input_)


# 导入即注册到全局能力注册表。
register_image_capability_provider(
    provider="pix",
    spec=ImageCapabilityProvider(
        resolve=resolve_pix_image_capability,
        register=register_pix_image_capability,
        clear=clear_pix_image_capability_overrides,
    ),
)
