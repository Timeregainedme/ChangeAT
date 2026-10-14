"""项目级信息提取 Agent：ElementExtractorAgent"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.schemas.skills.script_processing import StudioScriptExtractionDraft

_SCRIPT_EXTRACTOR_SYSTEM_PROMPT = """\
你是\"Studio 信息提取员\"。你的任务是：基于分镜结果（以及可选的一致性检查输出），输出可直接导入 Studio 的草稿结构 StudioScriptExtractionDraft（注意：ID 由导入 API 生成，因此这里全部使用 name 做引用键）。

输出 StudioScriptExtractionDraft：
- project_id（必填）
- chapter_id（必填）
- characters: [{name, description, voice_description?, costume_name?, prop_names[], tags[]}]
- scenes/props/costumes: [{name, description, tags[], prompt_template_id?, view_count}]
- shots: [{index, title, script_excerpt, scene_name?, character_names[], prop_names[], costume_names[], dialogue_lines[], actions[], semantic_suggestion?}]
  - dialogue_lines: [{index, text, line_mode, speaker_name?, target_name?}]
  - semantic_suggestion: {camera_shot?, angle?, movement?, duration?, action_beats[], notes?}

强约束：
- 同名实体在输出中只出现一次（全局去重）；shots 中引用必须使用同一名称
- shots.index 必须覆盖并对应输入分镜中的 index（不要跳号）
- 不要输出任何 id 字段（包括 char_001 等），由导入 API 生成
- 每个有对白（或明显发声）的角色都应输出 `voice_description`：用一两句中文描述其声音特征，
  覆盖年龄段（如青年/中年）、声线（如清亮/低沉/沙哑/温润）、气质（如温柔/冷峻/活泼）、
  语速与语调习惯（如语速偏快/沉稳缓慢）等；纯背景角色可省略。

一致性强约束（必须严格遵守，否则导入会失败）：
- 先输出全局 characters/scenes/props/costumes 列表，再输出 shots；并把它们视为“字典”。
- shots[*].character_names / prop_names / costume_names / scene_name 只能从对应全局列表的 name 中选择（完全一致的字符串），禁止生成任何未在全局列表中出现的新名字。
- 禁止“同义名/括号变体/临时称呼”漂移：例如禁止在 shots 中写「女子（群）」但在 characters 中没有该条目；禁止「仙女A」与「仙女 A」混用。
- 遇到群体角色/泛指角色（如“女子（群）”“群众”“村民们”）：必须在 characters 列表中创建一条同名角色（name 完全一致），并在 shots 中引用该 name。
- 对于难以确定是否同一角色的称呼：宁可在 characters 里拆成两条不同 name，也不要在 shots 中凭空换名。
- 输出 shots 之前，必须做“全集校验”并补齐缺失：所有 shots[*] 中出现的 character_names/prop_names/costume_names/scene_name 的名字集合，必须都能在对应全局列表（characters/props/costumes/scenes）的 name 中找到；如果有缺失，必须在全局列表中补齐对应条目（描述可最小化，但 name 必须完全一致），禁止用别名替换来绕过。
- 角色名/场景名必须原样保留字符细节：包括全角/半角括号、空格、标点，不要自动做任何规范化或替换（例如不能把「女子（群）」改成「女子(群)」或「女子 （群）」）。
- 严格区分：shots[*].title 是“镜头标题”（一句话描述该镜头画面/动作），不要拿它当作 scenes 的 scene 名；shots[*].scene_name 才是场景名称，必须来自 scenes 全局列表的 name。
- 除实体与对白外，还必须尽量补充镜头语言默认建议：`camera_shot` / `angle` / `movement` / `duration`。
- `camera_shot` 只能输出：ECU / CU / MCU / MS / MLS / LS / ELS。
- `angle` 只能输出：EYE_LEVEL / HIGH_ANGLE / LOW_ANGLE / BIRD_EYE / DUTCH / OVER_SHOULDER。
- `movement` 只能输出：STATIC / PAN / TILT / DOLLY_IN / DOLLY_OUT / TRACK / CRANE / HANDHELD / STEADICAM / ZOOM_IN / ZOOM_OUT。
- `duration` 必须输出正整数秒数；若无法判断，可省略。
- `action_beats` 需要输出 2-4 条按镜头内部时间顺序排列的动作拍点；每一条只描述一个主要动作或状态变化，不要写成长段文学描述。
- `semantic_suggestion` 是“镜头默认语义建议”，不是最终生成提示词，不要输出提示词式修饰文本。

输入：
- project_id
- chapter_id
- script_division_json（ScriptDivisionResult）
- consistency_json（可选）

只输出 JSON。
"""

SCRIPT_EXTRACTOR_PROMPT = PromptTemplate(
    input_variables=["project_id", "chapter_id", "script_division_json", "consistency_json"],
    template=(
        "## project_id\n{project_id}\n\n"
        "## chapter_id\n{chapter_id}\n\n"
        "## 一致性检查（可选）\n{consistency_json}\n\n"
        "## 分镜结果\n{script_division_json}\n\n"
        "## 输出\n"
    ),
)


class ElementExtractorAgent(AgentBase[StudioScriptExtractionDraft]):

    """项目级信息提取（最终输出）：输入分镜结果，产出全局实体表 + 逐镜关联。"""

    # 注册表键：发布后的模板提示词覆盖代码默认（见 prompt_registry.py）
    agent_key = 'element_extract'

    def _default_system_prompt(self) -> str:
        return _SCRIPT_EXTRACTOR_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return SCRIPT_EXTRACTOR_PROMPT

    @property
    def output_model(self) -> type[StudioScriptExtractionDraft]:
        return StudioScriptExtractionDraft

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        data.setdefault("project_id", "")
        data.setdefault("chapter_id", "")
        data.setdefault("script_text", "")
        for k in ("characters", "scenes", "props", "costumes", "shots"):
            if k not in data or not isinstance(data[k], list):
                data[k] = []
        return data
