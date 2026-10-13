"""优云智算 IndexTTS 2.5 语音能力声明与覆盖注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.integrations.audio_capabilities import (
    AudioCapabilityProvider,
    AudioModelCapability,
    register_audio_capability_provider,
)
from app.core.integrations.provider_capabilities import PrefixCapabilityStore

if TYPE_CHECKING:
    from app.core.contracts.audio_generation import AudioGenerationInput

# 平台只输出 WAV。
COMPSHARE_AUDIO_FORMATS = {"wav"}

_PRESET_DEFAULT = AudioModelCapability(
    supported_formats=set(COMPSHARE_AUDIO_FORMATS),
    supports_voice=True,
    supports_custom_voice=False,
    supports_speed=True,
    min_speed=0.5,
    max_speed=2.0,
    supports_emotion=True,
    max_emotion_chars=200,
    supports_language=True,
    max_text_chars=2000,
)

# IndexTTS-2.5-custom：使用自定义音色（voice.source="custom"）。
_CUSTOM_DEFAULT = AudioModelCapability(
    supported_formats=set(COMPSHARE_AUDIO_FORMATS),
    supports_voice=True,
    supports_custom_voice=True,
    supports_speed=True,
    min_speed=0.5,
    max_speed=2.0,
    supports_emotion=True,
    max_emotion_chars=200,
    supports_language=True,
    max_text_chars=2000,
)

# 后缀 "-custom" 的模型走自定义音色能力。
_STORE: PrefixCapabilityStore[AudioModelCapability] = PrefixCapabilityStore(
    provider="compshare_model_api",
    default=_PRESET_DEFAULT,
)
_STORE.register(model_prefix="-custom", capability=_CUSTOM_DEFAULT)


def register_compshare_audio_capability(
    *, model_prefix: str, capability: AudioModelCapability
) -> None:
    _STORE.register(model_prefix=model_prefix, capability=capability)


def clear_compshare_audio_capability_overrides() -> None:
    _STORE.clear()


def resolve_compshare_audio_capability(model: str | None) -> AudioModelCapability:
    return _STORE.resolve(model)


def resolve_compshare_voice_source(model: str | None) -> str:
    """模型名含 "custom" → 自定义音色，否则预设音色。"""
    name = (model or "").strip().lower()
    return "custom" if "custom" in name else "preset"


def validate_compshare_audio_options(input_: AudioGenerationInput) -> None:
    from app.core.contracts.audio_generation import AudioGenerationInput
    from app.core.integrations.audio_capabilities import validate_audio_options

    assert isinstance(input_, AudioGenerationInput)
    validate_audio_options(provider="compshare_model_api", model=input_.model, input_=input_)


register_audio_capability_provider(
    provider="compshare_model_api",
    spec=AudioCapabilityProvider(
        resolve=resolve_compshare_audio_capability,
        register=register_compshare_audio_capability,
        clear=clear_compshare_audio_capability_overrides,
    ),
)
