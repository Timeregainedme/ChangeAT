from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from app.core.contracts.video_generation import VideoRatio

class VideoGenerationTaskRequest(BaseModel):
    """视频生成任务请求。"""

    shot_id: str = Field(..., description="镜头 ID")
    reference_mode: Literal[
        "first", "last", "key", "first_last", "first_last_key", "text_only", "reference"
    ] = Field(
        ...,
        description=(
            "参考模式：first | last | key | first_last | first_last_key | text_only | reference；"
            "reference 为参考图模式（不使用分镜帧，参考图取自有序 IR 参考列表）"
        ),
    )
    # 文本模式必填；非文本模式可选作为补充描述
    prompt: str | None = Field(None, description="视频提示词（text_only / reference 必填）")
    images: list[str] = Field(
        default_factory=list,
        description=(
            "参考图 file_id 列表；帧模式数量需与 reference_mode 严格匹配，"
            "reference 模式由服务端按 IR 参考列表覆盖"
        ),
    )

    reference_audio_file_ids: list[str] = Field(
        default_factory=list,
        description=(
            "参考音频 file_id 列表（配音产物）。仅 reference 模式生效；"
            "会以对象存储公开 URL 提交给供应商（音频不支持 base64）。"
            "约束：最多 3 个，且必须同时存在参考图——音频不能单独使用。"
        ),
    )

    ratio: VideoRatio | None = Field(
        None,
        description=(
            "视频画幅比例，如 16:9 / 9:16；不传则继承分镜的 override_video_ratio，"
            "再继承项目的 default_video_ratio"
        ),
    )
    # A5：平台自带的提示词优化，默认关闭（由 Jellyfish 自己控制提示词内容）。
    use_context_ir: bool = Field(
        False, description="是否使用供应商平台自带的提示词优化，默认关闭"
    )
    skill_id: str | None = Field(
        None, description="平台提示词优化所用的 skill 标识，仅在 use_context_ir=true 时生效"
    )
    # seconds 由 ShotDetail.duration 自动确定；请求体不再接收覆盖值。
