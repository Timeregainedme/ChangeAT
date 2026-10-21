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
            # OpenCode Go（OpenCode Zen 网关）：OpenAI 兼容 /chat/completions，仅文本能力。
            # 平台内不认供应商的思考参数，故不登记 thinking_extra_body 映射，避免下发未知字段。
            ProviderSpec(
                key="opencode_go",
                display_name="OpenCode Go",
                aliases=(
                    "OpenCode Go",
                    "opencodego",
                    "opencode go",
                    "opencode",
                    "opencode zen",
                    "opencode-zen",
                    "opencode.ai",
                    "opencode.ai/zen/v1",
                    "opencode.ai/zen/go/v1",
                ),
                supported_categories=(ModelCategoryKey.text,),
                # 订阅通道：余额通道为 /zen/v1，两者 key 相同但计费不同。
                default_base_url="https://opencode.ai/zen/go/v1",
            ),
            # DeepSeek 官方 API：OpenAI 兼容格式，文本（含思考模式）能力。
            # 思考开关为 extra_body={"thinking": {"type": "enabled"|"disabled"}}，
            # 见 app/services/llm/provider_registry.py 的 thinking_extra_body 映射。
            ProviderSpec(
                key="deepseek",
                display_name="DeepSeek",
                aliases=(
                    "deepseek",
                    "深度求索",
                    "deepseek.com",
                    "api.deepseek.com",
                    "deepseek-chat",
                    "deepseek-flash",
                    "deepseek-v4-pro",
                ),
                supported_categories=(ModelCategoryKey.text,),
                default_base_url="https://api.deepseek.com/v1",
            ),
        ]
    )
