"""PIX 视频能力声明与覆盖注册。

PIX 视频接口用 `aspect_ratio` + `resolution`（如 `768p` / `2k`），不使用像素尺寸，
因此不设置 `ratio_to_size_mapping`（该字段仅 OpenAI 适配层使用）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.integrations.provider_capabilities import PrefixCapabilityStore
from app.core.integrations.video_capabilities import (
    ALLOWED_RATIOS,
    VideoCapabilityProvider,
    VideoModelCapability,
    register_video_capability_provider,
)

if TYPE_CHECKING:
    from app.core.contracts.video_generation import VideoGenerationInput

# minimax-h3 支持 4–15 秒、768P/2K；画幅取 PIX 与 Jellyfish 的交集。
PIX_VIDEO_DEFAULT_RESOLUTION = "768p"
PIX_VIDEO_ALLOWED_RESOLUTIONS = ("768p", "2k")

_PIX_DEFAULT = VideoModelCapability(
    supports_seed=False,
    supports_watermark=False,
    allowed_ratios=set(ALLOWED_RATIOS),
    default_ratio="16:9",
    min_seconds=4,
    max_seconds=15,
)

_STORE: PrefixCapabilityStore[VideoModelCapability] = PrefixCapabilityStore(
    provider="pix",
    default=_PIX_DEFAULT,
)


def register_pix_video_capability(*, model_prefix: str, capability: VideoModelCapability) -> None:
    _STORE.register(model_prefix=model_prefix, capability=capability)


def clear_pix_video_capability_overrides() -> None:
    _STORE.clear()


def resolve_pix_video_capability(model: str | None) -> VideoModelCapability:
    return _STORE.resolve(model)


def validate_pix_video_options(input_: VideoGenerationInput) -> None:
    """PIX 能力校验入口（避免调用侧传 provider 字面量）。"""
    from app.core.contracts.video_generation import VideoGenerationInput
    from app.core.integrations.video_capabilities import validate_video_options

    assert isinstance(input_, VideoGenerationInput)
    validate_video_options(provider="pix", model=input_.model, input_=input_)


register_video_capability_provider(
    provider="pix",
    spec=VideoCapabilityProvider(
        resolve=resolve_pix_video_capability,
        register=register_pix_video_capability,
        clear=clear_pix_video_capability_overrides,
    ),
)
