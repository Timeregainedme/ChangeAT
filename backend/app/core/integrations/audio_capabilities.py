"""音频（语音合成）生成能力约束与参数校验辅助。

DyeingTime 原本只有 text/image/video 三类生成能力；接入优云智算
IndexTTS 2.5 后新增 audio 类别，本模块承载其能力声明与校验。

与 image/video 能力表同构：能力接入采用注册表，新增供应商在自己的
能力模块里调用 `register_audio_capability_provider` 即可。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from threading import RLock
from typing import Callable

from app.core.contracts.audio_generation import AudioGenerationInput
from app.core.contracts.provider import ProviderKey

# 目前唯一可用的输出格式（优云智算语音接口只产出 WAV）。
DEFAULT_AUDIO_FORMATS = {"wav"}


@dataclass(frozen=True, slots=True)
class AudioModelCapability:
    """供应商/模型音频能力约束。"""

    supported_formats: set[str] | None = None
    supports_voice: bool = True
    # 是否支持自定义音色（需先调用平台接口创建音色再引用 voice_id）。
    supports_custom_voice: bool = False
    supports_speed: bool = True
    min_speed: float | None = 0.5
    max_speed: float | None = 2.0
    supports_emotion: bool = True
    max_emotion_chars: int | None = 200
    supports_language: bool = True
    max_text_chars: int | None = 2000


@dataclass(frozen=True, slots=True)
class AudioCapabilityProvider:
    """单个供应商的音频能力接入点。"""

    resolve: Callable[[str | None], AudioModelCapability]
    register: Callable[..., None] | None = None
    clear: Callable[[], None] | None = None


_EXTRA_CAPABILITY_MODULES: tuple[str, ...] = (
    "app.core.integrations.compshare.audio_capabilities",
)

_PROVIDERS: dict[str, AudioCapabilityProvider] = {}
_LOCK = RLock()
_BUILTINS_LOADED = False


def register_audio_capability_provider(*, provider: str, spec: AudioCapabilityProvider) -> None:
    """注册（或覆盖）某供应商的音频能力接入点。"""
    key = (provider or "").strip().lower()
    if not key:
        raise ValueError("provider must not be empty")
    with _LOCK:
        _PROVIDERS[key] = spec


def _load_builtin_audio_capability_providers() -> None:
    global _BUILTINS_LOADED
    with _LOCK:
        if _BUILTINS_LOADED:
            return

    for module_path in _EXTRA_CAPABILITY_MODULES:
        importlib.import_module(module_path)

    with _LOCK:
        _BUILTINS_LOADED = True


def _provider_entry(provider: ProviderKey, *, required: bool = True) -> AudioCapabilityProvider | None:
    _load_builtin_audio_capability_providers()
    key = (provider or "").strip().lower()
    with _LOCK:
        entry = _PROVIDERS.get(key)
    if entry is None and required:
        raise ValueError(f"No audio capability registered for provider={provider!r}")
    return entry


def register_audio_model_capability(
    *,
    provider: ProviderKey,
    model_prefix: str,
    capability: AudioModelCapability,
) -> None:
    """注册模型能力覆盖（按前缀匹配，大小写不敏感）。"""
    entry = _provider_entry(provider)
    assert entry is not None
    if entry.register is None:
        raise ValueError(f"provider={provider!r} does not support audio capability overrides")
    entry.register(model_prefix=model_prefix, capability=capability)


def clear_audio_model_capability_overrides(*, provider: ProviderKey | None = None) -> None:
    """清空能力覆盖；供测试或重置场景使用。"""
    _load_builtin_audio_capability_providers()
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


def resolve_audio_capability(*, provider: ProviderKey, model: str | None) -> AudioModelCapability:
    entry = _provider_entry(provider)
    assert entry is not None
    return entry.resolve(model)


def resolve_audio_format(*, provider: ProviderKey, model: str | None, requested_format: str | None) -> str:
    """解析最终输出格式，缺省取能力声明的第一个可用格式（通常为 wav）。"""
    cap = resolve_audio_capability(provider=provider, model=model)
    formats = cap.supported_formats or DEFAULT_AUDIO_FORMATS
    value = (requested_format or "").strip().lower()
    if value and value in formats:
        return value
    return sorted(formats)[0]


def validate_audio_options(
    *,
    provider: ProviderKey,
    model: str | None,
    input_: AudioGenerationInput,
) -> None:
    cap = resolve_audio_capability(provider=provider, model=model)
    label = f"provider={provider} model={model or '<default>'}"

    formats = cap.supported_formats or DEFAULT_AUDIO_FORMATS
    requested = (input_.format or "").strip().lower()
    if requested and requested not in formats:
        raise ValueError(f"Unsupported format for {label}: {input_.format}. Allowed: {sorted(formats)}")

    if cap.max_text_chars is not None and len(input_.text or "") > cap.max_text_chars:
        raise ValueError(f"text must be <= {cap.max_text_chars} characters for {label}")

    if input_.voice is not None and not cap.supports_voice:
        raise ValueError(f"voice is not supported by {label}")

    if input_.speed is not None and not cap.supports_speed:
        raise ValueError(f"speed is not supported by {label}")
    if input_.speed is not None and input_.speed > 0:
        if cap.min_speed is not None and input_.speed < cap.min_speed:
            raise ValueError(f"speed must be >= {cap.min_speed} for {label}")
        if cap.max_speed is not None and input_.speed > cap.max_speed:
            raise ValueError(f"speed must be <= {cap.max_speed} for {label}")

    if input_.emotion is not None:
        if not cap.supports_emotion:
            raise ValueError(f"emotion is not supported by {label}")
        if cap.max_emotion_chars is not None and len(input_.emotion) > cap.max_emotion_chars:
            raise ValueError(f"emotion must be <= {cap.max_emotion_chars} characters for {label}")

    if input_.language is not None and not cap.supports_language:
        raise ValueError(f"language is not supported by {label}")
