"""优云智算 MiniMax H3 视频能力声明与覆盖注册。"""

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

# H3 支持 adaptive / 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16；
# adaptive 无对应业务语义，故只声明与 Jellyfish VideoRatio 的交集。
COMPSHARE_VIDEO_RATIOS = set(ALLOWED_RATIOS)
COMPSHARE_VIDEO_RESOLUTIONS = ("480P", "768P", "1080P", "2K", "4K")
DEFAULT_COMPSHARE_VIDEO_RESOLUTION = "768P"
DEFAULT_COMPSHARE_VIDEO_DURATION_S = 5

# H3：4–30 秒。
_COMPSHARE_DEFAULT = VideoModelCapability(
    supports_seed=False,
    # 平台提供 aigc_watermark 开关。
    supports_watermark=True,
    allowed_ratios=set(COMPSHARE_VIDEO_RATIOS),
    default_ratio="16:9",
    min_seconds=4,
    max_seconds=30,
)

_STORE: PrefixCapabilityStore[VideoModelCapability] = PrefixCapabilityStore(
    provider="compshare_model_api",
    default=_COMPSHARE_DEFAULT,
)


def register_compshare_video_capability(
    *, model_prefix: str, capability: VideoModelCapability
) -> None:
    _STORE.register(model_prefix=model_prefix, capability=capability)


def clear_compshare_video_capability_overrides() -> None:
    _STORE.clear()


def resolve_compshare_video_capability(model: str | None) -> VideoModelCapability:
    return _STORE.resolve(model)


def validate_compshare_video_options(input_: VideoGenerationInput) -> None:
    from app.core.contracts.video_generation import VideoGenerationInput
    from app.core.integrations.video_capabilities import validate_video_options

    assert isinstance(input_, VideoGenerationInput)
    validate_video_options(provider="compshare_model_api", model=input_.model, input_=input_)


register_video_capability_provider(
    provider="compshare_model_api",
    spec=VideoCapabilityProvider(
        resolve=resolve_compshare_video_capability,
        register=register_compshare_video_capability,
        clear=clear_compshare_video_capability_overrides,
    ),
)
