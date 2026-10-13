"""生成能力共享的供应商类型契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProviderKey = Literal[
    "openai",
    "volcengine",
    # PIX 中转平台：OpenAI 风格 Bearer 鉴权；图片走 /api/v1/model-runtime/invoke，视频走 /v1/media/generate。
    "pix",
    # 优云智算「模型 API」（cp.compshare.cn）：MiniMax H3 视频 + IndexTTS 2.5 语音。
    "compshare_model_api",
]


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """执行生成任务时需要的供应商配置。"""

    provider: ProviderKey
    api_key: str
    base_url: str | None = None
