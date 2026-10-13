"""音频（语音合成）生成共享输入输出契约。"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.contracts.provider import ProviderKey

# 当前接入的供应商（优云智算 IndexTTS 2.5）只输出 WAV；保留 Literal 便于后续扩展。
AudioFormat = Literal["wav"]
AudioVoiceSource = Literal["preset", "custom"]


class AudioGenerationInput(BaseModel):
    """语音合成输入：文本必填，其余为音色/语速/情绪等可选控制项。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="待合成文本")
    model: Optional[str] = Field(None, description="模型名称（如 IndexTTS-2.5 / IndexTTS-2.5-custom）")
    voice: Optional[str] = Field(
        None,
        description="音色 ID（voice_id）；来源由 voice_source 或模型名决定",
    )
    voice_source: Optional[AudioVoiceSource] = Field(
        None,
        description="音色来源：preset 预设音色 / custom 自定义音色；缺省时按模型名推断",
    )
    language: Optional[str] = Field(None, description="语种，如 zh / en / ja；缺省由供应商决定")
    speed: Optional[float] = Field(
        None,
        description="语速倍率，取值区间由供应商能力声明（优云智算为 0.5–2.0）",
    )
    emotion: Optional[str] = Field(
        None,
        description="情绪描述（自然语言），如「轻柔地、略带哽咽」",
    )
    format: AudioFormat = Field("wav", description="输出音频格式，目前仅支持 wav")

    @model_validator(mode="after")
    def _strip_and_validate_text(self) -> "AudioGenerationInput":
        self.text = (self.text or "").strip()
        if not self.text:
            raise ValueError("text 不能为空")
        if self.emotion is not None:
            stripped = self.emotion.strip()
            self.emotion = stripped or None
        if self.voice is not None:
            self.voice = self.voice.strip() or None
        return self

    @model_validator(mode="after")
    def _validate_speed_range(self) -> "AudioGenerationInput":
        # 0 视为「未设置」，与供应商适配层的处理保持一致。
        if self.speed is not None and self.speed < 0:
            raise ValueError("speed 不能为负数")
        return self


class AudioGenerationResult(BaseModel):
    """语音合成统一结果。

    三种落地形态至少其一：
    - `url`：供应商返回的可访问地址；
    - `b64_data`：base64 音频内容（不含 data URI 前缀）；
    - `file_id`：已落库到素材库的文件 ID。
    """

    model_config = ConfigDict(extra="ignore")

    url: Optional[str] = Field(None, description="音频 URL")
    b64_data: Optional[str] = Field(None, description="base64 编码音频内容（不含 data URI 前缀）")
    file_id: Optional[str] = Field(None, description="素材库文件 ID")
    mime_type: Optional[str] = Field(None, description="音频 MIME 类型，如 audio/wav")
    duration_seconds: Optional[float] = Field(None, description="音频时长（秒），如供应商返回")
    provider: Optional[ProviderKey] = Field(None, description="供应商标识")
    provider_task_id: Optional[str] = Field(
        None,
        description="供应商内部任务 ID（若存在），用于调试/追踪",
    )
    status: Optional[str] = Field(None, description="供应商任务状态")

    @model_validator(mode="after")
    def _require_one_field(self) -> "AudioGenerationResult":
        if not self.url and not self.b64_data and not self.file_id:
            raise ValueError("AudioGenerationResult 需提供 url / b64_data / file_id 至少其一")
        return self
