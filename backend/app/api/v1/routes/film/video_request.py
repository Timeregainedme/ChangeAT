from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from app.core.contracts.video_generation import VideoRatio

class VideoGenerationTaskRequest(BaseModel):
    """视频生成任务请求。"""

    shot_id: str = Field(..., description="镜头 ID")
    reference_mode: Literal["first", "last", "key", "first_last", "first_last_key", "text_only"] = Field(
        ...,
        description="参考模式：first | last | key | first_last | first_last_key | text_only",
    )
    # 文本模式必填；非文本模式可选作为补充描述
    prompt: str | None = Field(None, description="视频提示词（text_only 必填）")
    images: list[str] = Field(
        default_factory=list,
        description="参考图 file_id 列表，数量需与 reference_mode 严格匹配",
    )

    ratio: VideoRatio | None = Field(
        None,
        description=(
            "视频画幅比例，如 16:9 / 9:16；不传则继承分镜的 override_video_ratio，"
            "再继承项目的 default_video_ratio"
        ),
    )
    # seconds 由 ShotDetail.duration 自动确定；请求体不再接收覆盖值。
