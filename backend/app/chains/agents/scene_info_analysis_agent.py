"""场景信息缺失分析 Agent：SceneInfoAnalysisAgent"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.schemas.skills.scene_info_analysis import SceneInfoAnalysisResult

_SCENE_INFO_SYSTEM_PROMPT = """\
你是"场景信息分析师"。你的任务是：当给定一份“原文场景描述”时，判断其中缺少哪些关键信息，导致无法生成合理的场景概念图/场景资产图（空间结构/时间天气/光源与氛围/材质与风格/关键陈设与地标/可视范围与景深等）。

要求：
- 输出必须严格服务于“可直接用于AI图像生成”的目的，optimized_description 需是一段连贯、正面、画面感强的描述。
- 原文仅作参照：只能在原文已明确给出的内容基础上进行顺滑连接或不改变原意的重排，不能修改、替换或弱化原文中的任何关键信息（地点、内外景、时间、事件状态、人物或关键物件等）。
- 当原文信息不足时，进行合理的保守补全式扩展，使 optimized_description 至少覆盖以下维度：场景类型与用途、空间布局与尺度（相对尺度亦可）、内外景与时间段、天气与环境状态（如适用）、光源方向与光质、整体色调与氛围、主要材质与风格年代、关键陈设/地标元素、地面与墙面细节、可见的环境痕迹（尘土/潮湿/破损/杂乱等）以及视线焦点与构图重心。
- issues：列出原文真正缺失的关键维度或存在的歧义点，并具体说明这些缺失如何影响场景生成的一致性、空间可读性或氛围准确性。
- optimized_description：在尽量保留原文原词原意的基础上，完整保留所有明确信息，并通过正面肯定句式补全缺失部分，形成一段可直接复制用于AI图像生成模型的完整场景描述。

禁止项（严格执行）：
- optimized_description 中绝对不允许出现“未被详细说明”“信息不详”“未知”“不明确”“假设”“比如”“可以设想”“类似”“通常”“可能”“大概”等任何模糊、不稳定、占位或推测性词语。
- 所有描述必须使用肯定、具体的正面语言，直接给出可视觉化的细节。
- issues 中只分析缺失或歧义，不在 optimized_description 中重复提及缺少的内容。
- 若原文已足够完整，issues 可为空或极简，optimized_description 仍需做结构化顺滑表达，但不得添加原文未暗示的关键事实。

只输出 JSON，符合 SceneInfoAnalysisResult 结构。
"""

SCENE_INFO_PROMPT = PromptTemplate(
    input_variables=["scene_context", "scene_description"],
    template=(
        "## 原文场景上下文（可为空）\n{scene_context}\n\n"
        "## 原文场景描述\n{scene_description}\n\n"
        "## 输出\n"
    ),
)


class SceneInfoAnalysisAgent(AgentBase[SceneInfoAnalysisResult]):

    """根据原文场景描述分析缺失信息，并输出优化后的可生成场景描述。"""

    # 注册表键：发布后的模板提示词覆盖代码默认（见 prompt_registry.py）
    agent_key = 'scene_info'

    def _default_system_prompt(self) -> str:
        return _SCENE_INFO_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return SCENE_INFO_PROMPT

    @property
    def output_model(self) -> type[SceneInfoAnalysisResult]:
        return SceneInfoAnalysisResult

    def analyze_scene_description(
        self, *, scene_description: str, scene_context: str | None = None
    ) -> SceneInfoAnalysisResult:
        return self.extract(
            scene_context=scene_context or "",
            scene_description=scene_description,
        )

    async def a_analyze_scene_description(
        self, *, scene_description: str, scene_context: str | None = None
    ) -> SceneInfoAnalysisResult:
        return await self.aextract(
            scene_context=scene_context or "",
            scene_description=scene_description,
        )

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        # 宽松兼容：issues/optimized_description 字段类型兜底，避免 strict schema 校验失败
        data = dict(data)
        issues = data.get("issues", [])
        if not isinstance(issues, list):
            data["issues"] = [str(issues)] if issues is not None else []
        if "optimized_description" not in data:
            data["optimized_description"] = ""

        optimized = data.get("optimized_description") or ""
        if isinstance(optimized, str) and optimized:
            fuzzy_markers = (
                "信息不详",
                "不详",
                "未知",
                "不明确",
                "未提及",
                "看不出来",
                "无法判断",
                "不确定",
                "暂时无法判断",
            )
            if any(m in optimized for m in fuzzy_markers):
                parts = optimized.replace("\n", " ").split("。")
                kept: list[str] = []
                for p in parts:
                    seg = p.strip()
                    if not seg:
                        continue
                    if any(m in seg for m in fuzzy_markers):
                        continue
                    kept.append(seg)
                cleaned = "。".join(kept).strip()
                data["optimized_description"] = cleaned or optimized

        return data

