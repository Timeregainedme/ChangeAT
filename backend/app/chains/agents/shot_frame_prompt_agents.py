"""镜头分镜首帧/尾帧/关键帧提示词生成 Agent：根据镜头信息生成对应帧的画面提示词。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase, _extract_json_from_text
from app.schemas.skills.shot_frame_prompt import ShotFramePromptResult


def _prepare_shot_frame_input(input_dict: dict[str, Any]) -> dict[str, Any]:
    """将 input_dict 转为 prompt 模板所需格式，mood_tags 转为字符串。"""
    out = dict(input_dict)
    if "mood_tags" in out and isinstance(out["mood_tags"], list):
        out["mood_tags"] = ", ".join(str(t) for t in out["mood_tags"])
    else:
        out.setdefault("mood_tags", "")
    if "action_beats" in out and isinstance(out["action_beats"], list):
        out["action_beats"] = "；".join(str(item) for item in out["action_beats"] if str(item).strip())
    else:
        out.setdefault("action_beats", "")
    for key in (
        "visual_style",
        "style",
        "unify_style",
        "camera_shot",
        "angle",
        "movement",
        "atmosphere",
        "shot_description",
        "vfx_type",
        "vfx_note",
        "duration",
        "scene_id",
        "dialog_summary",
        "action_beats",
        "action_beat_phases",
        "selected_action_beat_phase",
        "selected_action_beat_text",
        "character_context",
        "scene_context",
        "prop_context",
        "costume_context",
        "subject_priority",
        "previous_shot_title",
        "previous_shot_script_excerpt",
        "previous_shot_end_state",
        "next_shot_title",
        "next_shot_script_excerpt",
        "next_shot_start_goal",
        "continuity_guidance",
        "composition_anchor",
        "screen_direction_guidance",
        "frame_specific_guidance",
        "director_command_summary",
        "retry_guidance",
    ):
        if key not in out or out[key] is None:
            out[key] = ""
    if isinstance(out.get("unify_style"), bool):
        out["unify_style"] = "是" if out["unify_style"] else "否"
    out.setdefault("title", "")
    return out


_SHOT_FRAME_INPUT_VARS = [
    "script_excerpt",
    "title",
    "visual_style",
    "style",
    "unify_style",
    "camera_shot",
    "angle",
    "movement",
    "atmosphere",
    "shot_description",
    "mood_tags",
    "vfx_type",
    "vfx_note",
    "duration",
    "scene_id",
    "dialog_summary",
    "action_beats",
    "action_beat_phases",
    "selected_action_beat_phase",
    "selected_action_beat_text",
    "character_context",
    "scene_context",
    "prop_context",
    "costume_context",
    "subject_priority",
    "previous_shot_title",
    "previous_shot_script_excerpt",
    "previous_shot_end_state",
    "next_shot_title",
    "next_shot_script_excerpt",
    "next_shot_start_goal",
    "continuity_guidance",
    "composition_anchor",
    "screen_direction_guidance",
    "frame_specific_guidance",
    "director_command_summary",
    "retry_guidance",
]

_FRAME_FOCUS = {
    "首帧": "优先描述镜头开始时最先看到的画面建立信息，强调开场定场、主体初始状态与进入情境的第一印象；只表现触发瞬间或最初反应，不要直接写成后续完成动作、最终姿态或情绪爆发完成态。",
    "尾帧": "优先描述镜头结束时最终停留的画面状态，强调动作收束、人物结束姿态、视线落点或情绪余韵。",
    "关键帧": "优先捕捉镜头中最具代表性、最有戏剧张力或信息密度最高的瞬间，不必平均描述整个过程。",
}

_SHOT_FRAME_TEMPLATE = """你是一名专业影视分镜提示词设计师，需要为同一项目中的镜头生成**{frame_name}基础提示词**。

你的任务是生成“基础提示词”，只描述画面本身，供后续系统继续拼接图片映射说明。

## 强约束
1. 必须继承项目级画面表现形式与题材风格：{visual_style} / {style}
2. 项目是否要求统一风格：{unify_style}
3. 若镜头信息不足，优先向项目风格与已确认实体设定收敛，不要自由发散到其他风格
4. 当前镜头已确认的角色、场景、道具、服装名称必须原样保留，不得翻译、不得改名、不得替换为同义词
5. 不得输出“图1/图2”、不得输出“## 图片内容说明”、不得输出引用映射说明
6. 输出应为一句或几句简洁、可视化、可直接用于图像生成模型的中文描述
7. 尽量保持统一描述口径，优先按“景别/机位/运镜 -> 场景环境 -> 主体人物/关键对象 -> 动作状态 -> 氛围情绪 -> 风格收束”组织
8. 只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要输出其他文字
9. 当前帧关注重点：{frame_focus}
10. 主体优先级建议：{subject_priority}
11. 不要为了“写全信息”而平均罗列所有角色、道具、服装；优先突出主角色、主场景和主动作，其余元素仅在能强化当前画面时再进入提示词
12. 如果下面提供了“修正要求”，必须逐条满足后再输出最终结果
13. 若存在上一镜头信息，当前画面应尽量承接上一镜头的动作、空间方向、视线或情绪，不要像全新场景重新开局
14. 若存在下一镜头信息，当前画面应为下一镜头留下自然的动作或情绪收束，避免硬切
15. 尽量明确主体在画面中的相对位置、朝向与动作峰值，减少构图和轴线突变
16. 若提供了构图与空间锚点建议，应尽量落实到画面描述中，让主体位置、环境重心和空间方向更稳定
17. 若提供了朝向与视线建议，应保持人物左右关系、视线落点与反打轴线稳定，不要无故翻转
18. 若提供了当前帧专项建议，应优先满足该建议，确保首帧/关键帧/尾帧各自承担清晰职责
19. 若提供了导演指令摘要，应将其视为最高优先级的镜头执行约束，优先体现到最终画面描述中
20. 若当前为首帧，只能表现事件触发瞬间或最初反应，不要直接把后续完成动作、最终姿态或情绪爆发结果写进画面
21. 若当前为首帧且镜头存在连续动作链，应优先使用“刚开始 / 尚未完成 / 被打断”的未完成态表达，而不是结果态表达

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
镜头补充描述：{shot_description}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}
动作拍点：{action_beats}
动作拍点阶段：{action_beat_phases}
当前帧优先消费阶段：{selected_action_beat_phase}
当前帧主拍点：{selected_action_beat_text}

## 已确认实体上下文
角色：{character_context}
场景：{scene_context}
道具：{prop_context}
服装：{costume_context}

## 相邻镜头承接信息
上一镜头标题：{previous_shot_title}
上一镜头剧本摘录：{previous_shot_script_excerpt}
上一镜头结尾状态：{previous_shot_end_state}
下一镜头标题：{next_shot_title}
下一镜头剧本摘录：{next_shot_script_excerpt}
下一镜头起始目标：{next_shot_start_goal}
连续性建议：{continuity_guidance}
构图与空间锚点：{composition_anchor}
朝向与视线建议：{screen_direction_guidance}
当前帧专项建议：{frame_specific_guidance}
导演指令摘要：{director_command_summary}

修正要求：{retry_guidance}

## 输出（仅 {frame_name} 基础提示词，JSON：{{"prompt": "..."}}）
"""

def _build_frame_template(frame_name: str) -> str:
    return (
        _SHOT_FRAME_TEMPLATE.replace("{frame_name}", frame_name)
        .replace("{frame_focus}", _FRAME_FOCUS[frame_name])
    )


_FIRST_FRAME_TEMPLATE = _build_frame_template("首帧")
_LAST_FRAME_TEMPLATE = _build_frame_template("尾帧")
_KEY_FRAME_TEMPLATE = _build_frame_template("关键帧")

SHOT_FIRST_FRAME_PROMPT = PromptTemplate(input_variables=_SHOT_FRAME_INPUT_VARS, template=_FIRST_FRAME_TEMPLATE)
SHOT_LAST_FRAME_PROMPT = PromptTemplate(input_variables=_SHOT_FRAME_INPUT_VARS, template=_LAST_FRAME_TEMPLATE)
SHOT_KEY_FRAME_PROMPT = PromptTemplate(input_variables=_SHOT_FRAME_INPUT_VARS, template=_KEY_FRAME_TEMPLATE)

# 帧类型 -> 数据库提示词模板类别（B1：帧提示词模板开放到后台可编辑）
FRAME_CATEGORY_BY_TYPE: dict[str, str] = {
    "first": "frame_head_prompt",
    "last": "frame_tail_prompt",
    "key": "frame_key_prompt",
}

_FRAME_NAME_BY_TYPE: dict[str, str] = {
    "first": "首帧",
    "last": "尾帧",
    "key": "关键帧",
}

_BUILTIN_FRAME_PROMPTS: dict[str, PromptTemplate] = {
    "首帧": SHOT_FIRST_FRAME_PROMPT,
    "尾帧": SHOT_LAST_FRAME_PROMPT,
    "关键帧": SHOT_KEY_FRAME_PROMPT,
}


def normalize_frame_type(frame_type: str) -> str:
    """把外部传入的 frame_type 归一化为 first / last / key。"""
    key = str(frame_type or "").strip().lower()
    return key if key in _FRAME_NAME_BY_TYPE else "key"


def build_frame_prompt_template(
    frame_type: str,
    *,
    override: str | None = None,
) -> PromptTemplate:
    """构造帧提示词模板。

    优先使用后台（`prompt_templates` 表）配置的模板内容，为空或模板不合法时回退内置模板，
    保证链路永远可跑。`override` 由任务侧按 `FRAME_CATEGORY_BY_TYPE` 查库后注入。
    """
    frame_name = _FRAME_NAME_BY_TYPE[normalize_frame_type(frame_type)]
    text = (override or "").strip()
    if text:
        try:
            template = PromptTemplate(input_variables=_SHOT_FRAME_INPUT_VARS, template=text)
            # 后台模板只允许使用帧链路的既有变量，否则渲染时必然 KeyError，直接回退内置。
            unknown = [name for name in template.input_variables if name not in _SHOT_FRAME_INPUT_VARS]
            if not unknown:
                return template
        except Exception:  # 模板语法不合法：回退内置，不让整条链路失败
            return _BUILTIN_FRAME_PROMPTS[frame_name]
    return _BUILTIN_FRAME_PROMPTS[frame_name]


class _FramePromptTemplateMixin:
    """让帧提示词模板可被后台配置覆盖（B1）。"""

    _frame_type: str = "key"

    def __init__(
        self,
        *args: Any,
        frame_template: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._frame_template_override = frame_template

    @property
    def prompt_template(self) -> PromptTemplate:
        return build_frame_prompt_template(
            self._frame_type,
            override=self._frame_template_override,
        )


class ShotFirstFramePromptAgent(_FramePromptTemplateMixin, AgentBase[ShotFramePromptResult]):
    """镜头首帧提示词生成 Agent，输出可写入 ShotDetail.first_frame_prompt。"""

    _frame_type = "first"

    @property
    def output_model(self) -> type[ShotFramePromptResult]:
        return ShotFramePromptResult

    def format_output(self, raw: str) -> ShotFramePromptResult:
        json_str = _extract_json_from_text(raw)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return ShotFramePromptResult(prompt=raw.strip())
        if isinstance(data, dict) and "prompt" in data:
            return ShotFramePromptResult(prompt=str(data["prompt"]).strip())
        return ShotFramePromptResult(prompt=raw.strip())

    def extract(self, **kwargs: Any) -> ShotFramePromptResult:
        inp = _prepare_shot_frame_input(kwargs)
        raw = self.run(**inp)
        return self.format_output(raw)

    async def aextract(self, **kwargs: Any) -> ShotFramePromptResult:
        inp = _prepare_shot_frame_input(kwargs)
        raw = await self.arun(**inp)
        return self.format_output(raw)


class ShotLastFramePromptAgent(_FramePromptTemplateMixin, AgentBase[ShotFramePromptResult]):
    """镜头尾帧提示词生成 Agent，输出可写入 ShotDetail.last_frame_prompt。"""

    _frame_type = "last"

    @property
    def output_model(self) -> type[ShotFramePromptResult]:
        return ShotFramePromptResult

    def format_output(self, raw: str) -> ShotFramePromptResult:
        json_str = _extract_json_from_text(raw)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return ShotFramePromptResult(prompt=raw.strip())
        if isinstance(data, dict) and "prompt" in data:
            return ShotFramePromptResult(prompt=str(data["prompt"]).strip())
        return ShotFramePromptResult(prompt=raw.strip())

    def extract(self, **kwargs: Any) -> ShotFramePromptResult:
        inp = _prepare_shot_frame_input(kwargs)
        raw = self.run(**inp)
        return self.format_output(raw)

    async def aextract(self, **kwargs: Any) -> ShotFramePromptResult:
        inp = _prepare_shot_frame_input(kwargs)
        raw = await self.arun(**inp)
        return self.format_output(raw)


class ShotKeyFramePromptAgent(_FramePromptTemplateMixin, AgentBase[ShotFramePromptResult]):
    """镜头关键帧提示词生成 Agent，输出可写入 ShotDetail.key_frame_prompt。"""

    _frame_type = "key"

    @property
    def output_model(self) -> type[ShotFramePromptResult]:
        return ShotFramePromptResult

    def format_output(self, raw: str) -> ShotFramePromptResult:
        json_str = _extract_json_from_text(raw)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return ShotFramePromptResult(prompt=raw.strip())
        if isinstance(data, dict) and "prompt" in data:
            return ShotFramePromptResult(prompt=str(data["prompt"]).strip())
        return ShotFramePromptResult(prompt=raw.strip())

    def extract(self, **kwargs: Any) -> ShotFramePromptResult:
        inp = _prepare_shot_frame_input(kwargs)
        raw = self.run(**inp)
        return self.format_output(raw)

    async def aextract(self, **kwargs: Any) -> ShotFramePromptResult:
        inp = _prepare_shot_frame_input(kwargs)
        raw = await self.arun(**inp)
        return self.format_output(raw)
