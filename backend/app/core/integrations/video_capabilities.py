"""视频生成能力约束与参数映射辅助。

与 `image_capabilities` 同构：能力接入采用**注册表**，
内置 OpenAI / 火山引擎惰性注册，新增供应商在自己的能力模块里调用
`register_video_capability_provider` 即可。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from threading import RLock
from typing import Callable

from app.core.contracts.provider import ProviderKey
from app.core.contracts.video_generation import VideoGenerationInput, VideoRatio

ALLOWED_RATIOS = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}
DEFAULT_RATIO_TO_SIZE_MAPPING: dict[str, str] = {
    "16:9": "1280x720",
    "4:3": "1024x768",
    "1:1": "1024x1024",
    "3:4": "768x1024",
    "9:16": "720x1280",
    "21:9": "1680x720",
}


@dataclass(frozen=True, slots=True)
class VideoModelCapability:
    """供应商/模型能力约束。"""

    supports_seed: bool = True
    supports_watermark: bool = True
    allowed_ratios: set[str] | None = None
    default_ratio: str | None = None
    ratio_to_size_mapping: dict[str, str] | None = None
    min_seconds: int | None = 1
    max_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class VideoCapabilityProvider:
    """单个供应商的视频能力接入点。"""

    resolve: Callable[[str | None], VideoModelCapability]
    register: Callable[..., None] | None = None
    clear: Callable[[], None] | None = None


# 新增供应商的能力模块：导入即向本注册表注册自身。
_EXTRA_CAPABILITY_MODULES: tuple[str, ...] = (
    "app.core.integrations.pix.video_capabilities",
    "app.core.integrations.compshare.video_capabilities",
)

_PROVIDERS: dict[str, VideoCapabilityProvider] = {}
_LOCK = RLock()
_BUILTINS_LOADED = False


def register_video_capability_provider(*, provider: str, spec: VideoCapabilityProvider) -> None:
    """注册（或覆盖）某供应商的视频能力接入点。"""
    key = (provider or "").strip().lower()
    if not key:
        raise ValueError("provider must not be empty")
    with _LOCK:
        _PROVIDERS[key] = spec


def _load_builtin_video_capability_providers() -> None:
    global _BUILTINS_LOADED
    with _LOCK:
        if _BUILTINS_LOADED:
            return

    from app.core.integrations.openai.video_capabilities import (
        clear_openai_video_capability_overrides,
        register_openai_video_capability,
        resolve_openai_video_capability,
    )
    from app.core.integrations.volcengine.video_capabilities import (
        clear_volcengine_video_capability_overrides,
        register_volcengine_video_capability,
        resolve_volcengine_video_capability,
    )

    register_video_capability_provider(
        provider="openai",
        spec=VideoCapabilityProvider(
            resolve=resolve_openai_video_capability,
            register=register_openai_video_capability,
            clear=clear_openai_video_capability_overrides,
        ),
    )
    register_video_capability_provider(
        provider="volcengine",
        spec=VideoCapabilityProvider(
            resolve=resolve_volcengine_video_capability,
            register=register_volcengine_video_capability,
            clear=clear_volcengine_video_capability_overrides,
        ),
    )

    for module_path in _EXTRA_CAPABILITY_MODULES:
        importlib.import_module(module_path)

    with _LOCK:
        _BUILTINS_LOADED = True


def _provider_entry(provider: ProviderKey, *, required: bool = True) -> VideoCapabilityProvider | None:
    _load_builtin_video_capability_providers()
    key = (provider or "").strip().lower()
    with _LOCK:
        entry = _PROVIDERS.get(key)
    if entry is None and required:
        raise ValueError(f"No video capability registered for provider={provider!r}")
    return entry


def register_video_model_capability(
    *,
    provider: ProviderKey,
    model_prefix: str,
    capability: VideoModelCapability,
) -> None:
    """兼容入口：注册模型能力覆盖（按前缀匹配，大小写不敏感）。"""
    entry = _provider_entry(provider)
    assert entry is not None
    if entry.register is None:
        raise ValueError(f"provider={provider!r} does not support video capability overrides")
    entry.register(model_prefix=model_prefix, capability=capability)


def clear_video_model_capability_overrides(*, provider: ProviderKey | None = None) -> None:
    """兼容入口：清空能力覆盖；供测试或重置场景使用。"""
    _load_builtin_video_capability_providers()
    if provider is None:
        with _LOCK:
            entries = list(_PROVIDERS.values())
        for entry in entries:
            if entry.clear is not None:
                entry.clear()
        return
    entry = _provider_entry(provider, required=False)
    if entry is not None and entry.clear is not None:
        entry.clear()


def resolve_video_capability(*, provider: ProviderKey, model: str | None) -> VideoModelCapability:
    entry = _provider_entry(provider)
    assert entry is not None
    return entry.resolve(model)


def resolve_effective_ratio(input_: VideoGenerationInput) -> str | None:
    return input_.ratio


def resolve_default_ratio(*, provider: ProviderKey, model: str | None) -> str | None:
    cap = resolve_video_capability(provider=provider, model=model)
    if cap.default_ratio:
        return cap.default_ratio
    if cap.allowed_ratios:
        return sorted(cap.allowed_ratios)[0]
    return "16:9"


def derive_provider_size(
    *,
    provider: ProviderKey,
    model: str | None,
    ratio: VideoRatio,
) -> str | None:
    cap = resolve_video_capability(provider=provider, model=model)
    mapping = cap.ratio_to_size_mapping or DEFAULT_RATIO_TO_SIZE_MAPPING
    return mapping.get(ratio)


def validate_video_options(
    *,
    provider: ProviderKey,
    model: str | None,
    input_: VideoGenerationInput,
) -> None:
    cap = resolve_video_capability(provider=provider, model=model)
    if input_.ratio and cap.allowed_ratios is not None and input_.ratio not in cap.allowed_ratios:
        raise ValueError(
            f"Unsupported ratio for provider={provider} model={model or '<default>'}: {input_.ratio}. "
            f"Allowed: {sorted(cap.allowed_ratios)}"
        )
    if input_.seconds is not None:
        if cap.min_seconds is not None and input_.seconds < cap.min_seconds:
            raise ValueError(f"seconds must be >= {cap.min_seconds}")
        if cap.max_seconds is not None and input_.seconds > cap.max_seconds:
            raise ValueError(f"seconds must be <= {cap.max_seconds}")
    if input_.seed is not None and not cap.supports_seed:
        raise ValueError(f"seed is not supported by provider={provider} model={model or '<default>'}")
    if input_.watermark is not None and not cap.supports_watermark:
        raise ValueError(f"watermark is not supported by provider={provider} model={model or '<default>'}")
