"""真实文本 LLM 冒烟测试（`integration` marker，R-28）。

默认不执行（`addopts = "-m 'not integration'"`）；显式运行时若缺少凭据会自动 skip。

环境变量（OpenAI 兼容端点，DeepSeek / 阿里百炼 / PIX 文本均可）：
- ``JELLYFISH_INTEGRATION_BASE_URL``（回落 ``OPENAI_BASE_URL``，再回落 OpenAI 官方）
- ``JELLYFISH_INTEGRATION_API_KEY``（回落 ``OPENAI_API_KEY``）
- ``JELLYFISH_INTEGRATION_MODEL``（回落 ``gpt-4o-mini``）

示例::

    cd backend
    JELLYFISH_INTEGRATION_BASE_URL=https://api.deepseek.com/v1 \
    JELLYFISH_INTEGRATION_API_KEY=sk-xxx \
    JELLYFISH_INTEGRATION_MODEL=deepseek-flash \
    uv run pytest tests -m integration -q
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI


def _integration_env() -> tuple[str, str, str] | None:
    api_key = os.getenv("JELLYFISH_INTEGRATION_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    base_url = (
        os.getenv("JELLYFISH_INTEGRATION_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    )
    model = os.getenv("JELLYFISH_INTEGRATION_MODEL") or "gpt-4o-mini"
    return base_url, api_key, model


@pytest.mark.integration
def test_real_text_llm_returns_non_empty_content() -> None:
    """真实供应商能返回非空文本（验证凭据、base_url、模型名三者可用）。"""
    env = _integration_env()
    if env is None:
        pytest.skip("未设置 JELLYFISH_INTEGRATION_API_KEY / OPENAI_API_KEY，跳过真实 LLM 冒烟测试。")
    base_url, api_key, model = env

    llm = ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0)
    result = llm.invoke([HumanMessage(content="只回复两个字：可以")])

    assert isinstance(result.content, str)
    assert result.content.strip()


@pytest.mark.integration
def test_deepseek_thinking_toggle_is_accepted_by_real_provider() -> None:
    """DeepSeek 的真实端点接受 `extra_body={"thinking": {"type": ...}}` 两种取值。

    只对 DeepSeek 端点生效；其它端点直接 skip（该字段是 DeepSeek 专有）。
    """
    env = _integration_env()
    if env is None:
        pytest.skip("未设置 JELLYFISH_INTEGRATION_API_KEY / OPENAI_API_KEY，跳过真实 LLM 冒烟测试。")
    base_url, api_key, model = env
    if "deepseek" not in base_url.lower():
        pytest.skip(f"当前 base_url 不是 DeepSeek 端点（{base_url}），跳过 thinking 开关实测。")

    for enabled in (True, False):
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            extra_body={"thinking": {"type": "enabled" if enabled else "disabled"}},
        )
        result = llm.invoke([HumanMessage(content="只回复两个字：可以")])
        assert isinstance(result.content, str)
        assert result.content.strip()
