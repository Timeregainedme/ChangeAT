"""变体分析 Agent：VariantAnalyzerAgent"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.schemas.skills.script_processing import VariantAnalysisResult

_VARIANT_ANALYZER_SYSTEM_PROMPT = """\
你是\"变体分析师\"。分析实体变体（特别是角色服装变化），构建时间线，生成变体建议。
输出 VariantAnalysisResult：costume_timelines.timeline_entries 使用 {shot_index, scene_id, costume_note, changes, evidence}；variant_suggestions 可带 evidence。
只输出 JSON，符合 VariantAnalysisResult 结构。
"""

VARIANT_ANALYZER_PROMPT = PromptTemplate(
    input_variables=["merged_library_json", "all_extractions_json", "script_division_json"],
    template=(
        "## 脚本分镜(来自上一步)\n{script_division_json}\n\n"
        "## 合并后的实体库\n{merged_library_json}\n\n"
        "## 所有镜头提取结果\n{all_extractions_json}\n\n"
        "## 输出\n"
    ),
)


class VariantAnalyzerAgent(AgentBase[VariantAnalysisResult]):

    """服装/外形变体检测与建议：输入实体库+全镜提取，输出变体分析结果。"""

    # 注册表键：发布后的模板提示词覆盖代码默认（见 prompt_registry.py）
    agent_key = 'variant_analyze'

    def _default_system_prompt(self) -> str:
        return _VARIANT_ANALYZER_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return VARIANT_ANALYZER_PROMPT

    @property
    def output_model(self) -> type[VariantAnalysisResult]:
        return VariantAnalysisResult

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化变体分析结果。"""
        data = dict(data)
        if "costume_timelines" not in data or not isinstance(data["costume_timelines"], list):
            data["costume_timelines"] = []
        if "variant_suggestions" not in data or not isinstance(data["variant_suggestions"], list):
            data["variant_suggestions"] = []
        if "chapter_variants" not in data or not isinstance(data["chapter_variants"], dict):
            data["chapter_variants"] = {}
        # 补齐可选 evidence 字段，避免 strict schema 校验失败
        for tl in data.get("costume_timelines", []) or []:
            if not isinstance(tl, dict):
                continue
            entries = tl.get("timeline_entries")
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict) and "evidence" not in e:
                        e["evidence"] = []
        for s in data.get("variant_suggestions", []) or []:
            if isinstance(s, dict) and "evidence" not in s:
                s["evidence"] = []
        return data

