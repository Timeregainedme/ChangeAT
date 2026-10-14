"""智能精简 Agent：ScriptSimplifierAgent"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.schemas.skills.script_processing import ScriptSimplificationResult

_SCRIPT_SIMPLIFIER_SYSTEM_PROMPT = """\
你是"智能精简剧本Agent"。你的任务是：在不改变核心剧情走向的前提下精简剧本。

强约束：
- 必须保留剧情主体（关键事件、关键冲突、关键转折、结局/阶段性结果）。
- 必须保证剧情连续（时间顺序、因果关系、角色动机衔接不能断裂）。
- 禁止凭空新增关键设定或关键事件。
- 精简优先删除冗余重复描述、弱信息修饰、对主线无贡献的枝节句。
- 输出语言风格尽量贴近原文叙述口吻。

输出 ScriptSimplificationResult：
- simplified_script_text：精简后的完整文本
- simplification_summary：精简策略摘要（说明删改了什么、为何不影响主线）

只输出 JSON。
"""

SCRIPT_SIMPLIFIER_PROMPT = PromptTemplate(
    input_variables=["script_text"],
    template="## 原文剧本\n{script_text}\n\n## 输出\n",
)


class ScriptSimplifierAgent(AgentBase[ScriptSimplificationResult]):

    """智能精简剧本 Agent：输入剧本文本，输出保留主线与连续性的精简版本。"""

    # 注册表键：发布后的模板提示词覆盖代码默认（见 prompt_registry.py）
    agent_key = 'script_simplify'

    def _default_system_prompt(self) -> str:
        return _SCRIPT_SIMPLIFIER_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return SCRIPT_SIMPLIFIER_PROMPT

    @property
    def output_model(self) -> type[ScriptSimplificationResult]:
        return ScriptSimplificationResult

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        if "simplified_script_text" not in data:
            # 兼容模型可能沿用旧字段名
            data["simplified_script_text"] = str(data.get("optimized_script_text") or "")
        if "simplification_summary" not in data:
            data["simplification_summary"] = str(data.get("change_summary") or "")
        return data

