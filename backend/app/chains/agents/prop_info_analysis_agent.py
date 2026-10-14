"""道具信息缺失分析 Agent：PropInfoAnalysisAgent"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.schemas.skills.prop_info_analysis import PropInfoAnalysisResult

_PROP_INFO_SYSTEM_PROMPT = """\
你是"道具信息分析师"。你的任务是：当给定一份“原文道具描述”时，判断其中缺少哪些关键信息，导致无法生成合理的道具资产图（外观结构/材质工艺/尺寸比例/使用方式/状态细节/年代与风格/标识与磨损等）。

要求：
- 输出必须严格服务于“可直接用于AI图像生成”的目的，optimized_description 需是一段连贯、正面、画面感强的描述。
- 原文仅作参照：只能在原文已明确给出的内容基础上进行顺滑连接或不改变原意的重排，不能修改、替换或弱化原文中的任何关键信息（名称、用途、归属、时代与风格、材质、状态等）。
- 当原文信息不足时，进行合理的保守补全式扩展，使 optimized_description 至少覆盖以下维度：道具名称与类型、整体形态与结构、材质与表面质感、颜色与关键细节、尺寸与比例（相对尺度亦可）、使用方式与功能特征、状态（新旧/磨损/污渍/破损/可动部件等）、标识或独特特征，并可适度加入与剧情一致的环境痕迹（需与整体道具目标一致）。
- issues：列出原文真正缺失的关键维度或存在的歧义点，并具体说明这些缺失如何影响道具资产生成的一致性、结构可读性或细节完整性。
- optimized_description：在尽量保留原文原词原意的基础上，完整保留所有明确信息，并通过正面肯定句式补全缺失部分，形成一段可直接复制用于AI图像生成模型的完整道具描述。

禁止项（严格执行）：
- optimized_description 中绝对不允许出现“未被详细说明”“信息不详”“未知”“不明确”“假设”“比如”“可以设想”“类似”“通常”“可能”“大概”等任何模糊、不稳定、占位或推测性词语。
- 所有描述必须使用肯定、具体的正面语言，直接给出可视觉化的细节。
- issues 中只分析缺失或歧义，不在 optimized_description 中重复提及缺少的内容。
- 若原文已足够完整，issues 可为空或极简，optimized_description 仍需做结构化顺滑表达，但不得添加原文未暗示的关键事实。

只输出 JSON，符合 PropInfoAnalysisResult 结构。
"""

PROP_INFO_PROMPT = PromptTemplate(
    input_variables=["prop_context", "prop_description"],
    template=(
        "## 原文道具上下文（可为空）\n{prop_context}\n\n"
        "## 原文道具描述\n{prop_description}\n\n"
        "## 输出\n"
    ),
)


class PropInfoAnalysisAgent(AgentBase[PropInfoAnalysisResult]):

    """根据原文道具描述分析缺失信息，并输出优化后的可生成道具描述。"""

    # 注册表键：发布后的模板提示词覆盖代码默认（见 prompt_registry.py）
    agent_key = 'prop_info'

    def _default_system_prompt(self) -> str:
        return _PROP_INFO_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return PROP_INFO_PROMPT

    @property
    def output_model(self) -> type[PropInfoAnalysisResult]:
        return PropInfoAnalysisResult

    def analyze_prop_description(
        self, *, prop_description: str, prop_context: str | None = None
    ) -> PropInfoAnalysisResult:
        return self.extract(
            prop_context=prop_context or "",
            prop_description=prop_description,
        )

    async def a_analyze_prop_description(
        self, *, prop_description: str, prop_context: str | None = None
    ) -> PropInfoAnalysisResult:
        return await self.aextract(
            prop_context=prop_context or "",
            prop_description=prop_description,
        )

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        # 宽松兼容：issues/optimized_description 字段类型兜底，避免 strict schema 校验失败
        data = dict(data)
        issues = data.get("issues", [])
        if not isinstance(issues, list):
            data["issues"] = [str(issues)] if issues is not None else []
        if "optimized_description" not in data:
            data["optimized_description"] = ""

        # 兜底清理：若模型把“信息不详/未知”等占位句写进 optimized_description，则移除这些句子
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

