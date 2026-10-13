from __future__ import annotations

from app.models.llm import ModelCategoryKey
from app.services.llm.provider_registry import ProviderSpec, register_many


def bootstrap_builtin_providers() -> None:
    register_many(
        [
            ProviderSpec(
                key="openai",
                display_name="OpenAI",
                aliases=("openai",),
                supported_categories=(
                    ModelCategoryKey.text,
                    ModelCategoryKey.image,
                    ModelCategoryKey.video,
                ),
                default_base_url="https://api.openai.com/v1",
            ),
            ProviderSpec(
                key="volcengine",
                display_name="火山引擎",
                aliases=("火山引擎", "volcengine", "volc", "doubao", "bytedance", "ark"),
                supported_categories=(ModelCategoryKey.image, ModelCategoryKey.video),
                default_base_url="https://ark.cn-beijing.volces.com/api/v3",
            ),
            ProviderSpec(
                key="aliyun_bailian",
                display_name="阿里百炼",
                aliases=("阿里百炼", "aliyun", "bailian", "dashscope"),
                supported_categories=(ModelCategoryKey.text,),
                default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            # PIX 多模型中转：兼容 OpenAI 风格 Bearer 鉴权，图片/视频能力齐备。
            ProviderSpec(
                key="pix",
                display_name="PIX",
                aliases=("pix", "pix中转", "token6688", "pix.token6688.com"),
                supported_categories=(ModelCategoryKey.image, ModelCategoryKey.video),
                default_base_url="https://pix.token6688.com",
            ),
            # 优云智算「模型 API」：MiniMax H3 视频 + IndexTTS 2.5 语音。
            ProviderSpec(
                key="compshare_model_api",
                display_name="优云智算 模型 API",
                aliases=(
                    "优云智算 模型 API",
                    "优云智算模型API",
                    "优云智算",
                    "compshare_model_api",
                    "compshare model api",
                    "compsharemodelapi",
                    "compshare",
                    "cp.compshare.cn",
                ),
                supported_categories=(ModelCategoryKey.video, ModelCategoryKey.audio),
                default_base_url="https://cp.compshare.cn",
            ),
        ]
    )
