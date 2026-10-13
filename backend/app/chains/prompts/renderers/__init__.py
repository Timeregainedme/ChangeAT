"""提示词渲染器：把目标模型无关的 IR 输出为具体模型需要的格式。

新增/更换模型时只需在此包内新增一个 renderer，并在 `get_video_renderer` /
`get_image_renderer` 里登记，上游构建逻辑无需改动。
"""

from __future__ import annotations

from typing import Any, Callable

from app.chains.prompts.ir import IRPrompt
from app.chains.prompts.renderers.h3 import (
    H3Prose,
    H3RenderResult,
    render_h3,
    render_h3_base,
    render_h3_reference,
)

VideoRenderer = Callable[..., H3RenderResult]

# 走 H3 官方英文正文的模型标识（provider 名 / 模型名前缀）。
_H3_PROVIDER_NAMES = {"compshare", "compshare_model_api", "modelverse", "minimax"}
_H3_MODEL_KEYWORDS = ("minimax", "h3", "hailuo")


def uses_h3_prompt_format(*, provider: str = "", model: str = "") -> bool:
    """判断该 provider/model 是否走 H3 官方提示词格式。"""
    provider_key = str(provider or "").strip().lower()
    model_key = str(model or "").strip().lower()
    if provider_key in _H3_PROVIDER_NAMES:
        return True
    return any(keyword in model_key for keyword in _H3_MODEL_KEYWORDS)


def get_video_renderer(*, provider: str = "", model: str = "") -> VideoRenderer:
    """按 provider/model 返回视频提示词渲染器。

    当前只有 H3 一个渲染器；其它模型在补上 renderer 之前统一回落到 H3 渲染器，
    以保证「换模型只加渲染器」的扩展点在代码里是显式的。
    """
    return render_h3


def render_video_prompt(
    ir: IRPrompt,
    *,
    provider: str = "",
    model: str = "",
    prose: H3Prose | None = None,
) -> H3RenderResult:
    """渲染视频提示词 IR。"""
    renderer: Any = get_video_renderer(provider=provider, model=model)
    return renderer(ir, prose=prose)


__all__ = [
    "H3Prose",
    "H3RenderResult",
    "get_video_renderer",
    "render_h3",
    "render_h3_base",
    "render_h3_reference",
    "render_video_prompt",
    "uses_h3_prompt_format",
]
