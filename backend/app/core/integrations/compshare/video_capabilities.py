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
# adaptive 无对应业务语义，故只声明与 DyeingTime VideoRatio 的交集。
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
    # 供应商用大写档位，这里统一转成小写暴露给业务层
    allowed_resolutions={r.lower() for r in COMPSHARE_VIDEO_RESOLUTIONS},
    default_resolution=DEFAULT_COMPSHARE_VIDEO_RESOLUTION.lower(),
    min_seconds=4,
    max_seconds=30,
)

# H3 参考素材硬约束：参考图 ≤9、参考视频 ≤3、参考音频 ≤3、总数 ≤12；
# 参考音频不能单独使用；首尾帧素材不能与参考素材混用。
H3_MAX_REFERENCE_IMAGES = 9
H3_MAX_REFERENCE_VIDEOS = 3
H3_MAX_REFERENCE_AUDIOS = 3
H3_MAX_REFERENCE_TOTAL = 12
# 官方 MAX_PROMPT_CHARS。
H3_MAX_PROMPT_CHARS = 7000


def _has_payload(value: str | None) -> bool:
    return bool(value and value.strip())


def validate_h3_reference_material(input_: VideoGenerationInput) -> None:
    """校验 H3 素材硬约束：首尾帧与参考素材互斥、参考图数量上限、提示词长度上限。"""
    references = [item for item in (input_.reference_images or []) if _has_payload(item)]
    frames = [
        item
        for item in (
            input_.first_frame_base64,
            input_.last_frame_base64,
            input_.key_frame_base64,
        )
        if _has_payload(item)
    ]
    audios = [item for item in (input_.reference_audios or []) if _has_payload(item)]
    if references and frames:
        raise ValueError("MiniMax H3 的首尾帧素材不能与参考图片、参考视频或参考音频混用")
    if len(references) > H3_MAX_REFERENCE_IMAGES:
        raise ValueError(
            f"MiniMax H3 参考图片最多 {H3_MAX_REFERENCE_IMAGES} 张，当前 {len(references)} 张"
        )
    if len(audios) > H3_MAX_REFERENCE_AUDIOS:
        raise ValueError(
            f"MiniMax H3 参考音频最多 {H3_MAX_REFERENCE_AUDIOS} 个，当前 {len(audios)} 个"
        )
    # 官方约束：参考音频不能单独使用，必须同时提供至少一张参考图或一个参考视频。
    if audios and not references:
        raise ValueError(
            "MiniMax H3 的参考音频不能单独使用：必须同时提供至少一张参考图或一个参考视频"
        )
    if audios and frames:
        raise ValueError("MiniMax H3 的首尾帧素材不能与参考音频混用")
    prompt_chars = len((input_.prompt or "").strip())
    if prompt_chars > H3_MAX_PROMPT_CHARS:
        raise ValueError(
            f"MiniMax H3 提示词最多 {H3_MAX_PROMPT_CHARS} 字符，当前 {prompt_chars} 字符"
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
    validate_h3_reference_material(input_)
    validate_video_options(provider="compshare_model_api", model=input_.model, input_=input_)


register_video_capability_provider(
    provider="compshare_model_api",
    spec=VideoCapabilityProvider(
        resolve=resolve_compshare_video_capability,
        register=register_compshare_video_capability,
        clear=clear_compshare_video_capability_overrides,
    ),
)
