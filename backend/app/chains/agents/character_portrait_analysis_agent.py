"""人物画像缺失信息分析 Agent：CharacterPortraitAnalysisAgent"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.schemas.skills.character_portrait import CharacterPortraitAnalysisResult

_CHARACTER_PORTRAIT_SYSTEM_PROMPT = """\
你是\"人物画像分析师\"。你的任务是：当给定一份“原文人物描述”时，判断其中缺少哪些关键信息，导致无法生成合理的人物画像（外貌/服装造型/气质/性格倾向/年龄感/显著标志特征/背景或动机线索等）。

要求：
- 输出必须严格服务于“可直接用于AI图像生成”的目的，optimized_description 需是一段连贯、正面、画面感强的描述。
- 原文仅作参照：只能在原文已明确给出的内容基础上进行顺滑连接或不改变原意的重排，不能修改、替换或弱化原文中的任何人物信息（年龄、性别、外貌特征、性格描述等）。
- 当原文信息不足时，进行合理的保守补全式扩展，使 optimized_description 至少覆盖以下维度：年龄、性别、性格倾向、外貌（面部特征、体态、肤质、发型等）、服装造型、气质、显著标志特征，并可适度加入背景或动机线索（需与整体画像目标一致）。
- issues：列出原文真正缺失的关键维度或存在的歧义点，并具体说明这些缺失如何影响画像生成的一致性、视觉完整性或人物生动感。
- optimized_description：在尽量保留原文原词原意的基础上，完整保留所有明确信息，并通过正面肯定句式补全缺失部分，形成一段可直接复制用于AI图像生成模型的完整人物描述。

禁止项（严格执行）：
- optimized_description 中绝对不允许出现“未被详细说明”“信息不详”“未知”“不明确”“假设”“比如”“可以设想”“类似”“通常”“可能”“大概”等任何模糊、不稳定、占位或推测性词语。
- 所有描述必须使用肯定、具体的正面语言，直接给出可视觉化的细节。
- issues 中只分析缺失或歧义，不在 optimized_description 中重复提及缺少的内容。
- 若原文已足够完整，issues 可为空或极简，optimized_description 仍需做结构化顺滑表达，但不得添加原文未暗示的关键事实。

只输出 JSON，符合 CharacterPortraitAnalysisResult 结构。
"""

CHARACTER_PORTRAIT_PROMPT = PromptTemplate(
    input_variables=["character_context", "character_description"],
    template=(
        "## 原文人物上下文（可为空）\n{character_context}\n\n"
        "## 原文人物描述\n{character_description}\n\n"
        "## 输出\n"
    ),
)


class CharacterPortraitAnalysisAgent(AgentBase[CharacterPortraitAnalysisResult]):

    """根据原文人物描述分析缺失信息，并输出优化后的可生成画像描述。"""

    # 注册表键：发布后的模板提示词覆盖代码默认（见 prompt_registry.py）
    agent_key = 'character_portrait'

    def _default_system_prompt(self) -> str:
        return _CHARACTER_PORTRAIT_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return CHARACTER_PORTRAIT_PROMPT

    @property
    def output_model(self) -> type[CharacterPortraitAnalysisResult]:
        return CharacterPortraitAnalysisResult

    def analyze_character_description(
        self, *, character_description: str, character_context: str | None = None
    ) -> CharacterPortraitAnalysisResult:
        return self.extract(
            character_context=character_context or "",
            character_description=character_description,
        )

    async def a_analyze_character_description(
        self, *, character_description: str, character_context: str | None = None
    ) -> CharacterPortraitAnalysisResult:
        return await self.aextract(
            character_context=character_context or "",
            character_description=character_description,
        )

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        # 宽松兼容：issues/optimized_description 字段类型兜底，避免 strict schema 校验失败
        data = dict(data)
        issues = data.get("issues", [])
        if not isinstance(issues, list):
            data["issues"] = [str(issues)] if issues is not None else []
        if "optimized_description" not in data:
            data["optimized_description"] = ""

        # 兜底清理：若模型把“信息不详/未知”等占位句写进 optimized_description，
        # 则移除这些句子，避免影响后续“可生成画像”的正向描述质量。
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
                # 如果清理后为空，则保留原文（避免误删导致内容全空）
                data["optimized_description"] = cleaned or optimized

        return data

