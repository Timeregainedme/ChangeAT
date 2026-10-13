"""H3 视频提示词 Agent：把分镜 IR 写成 MiniMax H3 官方的英文六段正文。

分工：
- `app/chains/prompts/ir.py` 负责把分镜上下文整理成**与模型无关**的 IR；
- 本 Agent 负责把 IR 写成**符合 H3 官方格式**的英文正文（`H3Prose`）；
- `app/chains/prompts/renderers/h3.py` 负责把正文装配成最终提示词并校验结构。

这样换模型时只需新增「IR → 该模型正文」的 Agent 与渲染器，不必改动分镜链路。
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.chains.prompts import short_drama_rules as rules
from app.chains.prompts.ir import IRPrompt
from app.chains.prompts.renderers.h3 import H3Prose

_SYSTEM_PROMPT = "\n".join(
    [
        "你是竖屏短剧的分镜视频提示词工程师，负责为 MiniMax H3 视频模型撰写英文提示词正文。",
        "",
        "格式纪律（违反即为不合格输出）：",
        "- 正文一律英文；仅 <d> 内的台词保留原语言；",
        "- 段落名（subject_definitions / summary / retention_analysis / detailed_description /",
        "  overall_soundscape / non_diegetic_music）由系统拼装，你只写各段落的正文；",
        "- subject_definitions：每个内容单元一行，以 `<Subject N>:` 开头；"
        "由参考图定义的内容单元在行内标注来源，如 `(source: <Picture 1>)`；",
        "- summary：一段英文，以方括号任务类型前缀开头（如 `[reference generation]`），"
        "只允许引用已定义的 <Subject N>，不引入新标签；",
        "- retention_analysis：每个 <Subject N> 一行，格式 "
        "`<Subject N> (appears in [Shot N]): marker - 说明`；可见内容标记只能用 "
        "fully_preserved / partially_preserved / attribute_transfer / weak_reference；"
        "此处不得写 (Sx)；",
        "- detailed_description：先用 1–2 句英文确立风格，再写 `[Shot 1]`（首个镜头不带时间戳），"
        "后续镜头写 `[Shot N] At MM:SS.mmm, ...`；运镜写成完整英文自然句"
        "（运动类型 + 幅度 + 速度）；说话人用稳定的 (S1)/(S2)，台词写成 `<d>[Chinese] …</d>`；",
        "- overall_soundscape：只写环境音与物理拟音，对白/歌唱不在此重复；",
        "- non_diegetic_music：没有背景音乐就写 N/A；",
        "- 不使用 'cinematic' / 'beautiful' / 'high quality' 这类空泛词，"
        "改用具体的构图、光线、材质、动作与声音细节；",
        "- 不要输出任何解释、标题或代码块标记。",
        "",
        "短剧写作纪律：",
        rules.summarize_rules(rules.SHORT_DRAMA_SYSTEM_GUIDELINES),
    ]
)

_USER_TEMPLATE = """请为下面这个竖屏短剧镜头撰写 H3 视频提示词正文。

## 基本参数
- 时长：{duration_seconds} 秒
- 画面比例：{aspect_ratio}
- 题材 / 视觉风格：{genre} / {visual_style}

## 参考素材（按上传顺序编号）
{reference_block}

## 内容单元（已分配 H3 标签，正文必须原样沿用这些标签与编号）
{subject_block}

## 台词
{dialogue_block}

## 镜头信息
{shot_block}

## 短剧写作规则
{rules_block}

## 禁用词
{banned_block}
"""


def _reference_block(ir: IRPrompt) -> str:
    if not ir.references:
        return "（本镜头没有可用参考图）"
    lines: list[str] = []
    for index, ref in enumerate(ir.references, start=1):
        lines.append(
            f"{ref.token}（H3 标签 <Picture {index}>）："
            + rules.build_reference_binding_line(ref.token, ref.name, ref.kind)
        )
    return "\n".join(lines)


def _subject_block(ir: IRPrompt) -> str:
    lines: list[str] = []
    for subject in ir.subjects:
        speaker = f" speaker={subject.speaker_id}" if subject.speaker_id else ""
        sources = ", ".join(subject.source_tokens) or "-"
        lines.append(
            f"{subject.label} = {subject.kind}「{subject.name}」sources={sources}{speaker}"
        )
    return "\n".join(lines) or "-"


def _dialogue_block(ir: IRPrompt) -> str:
    lines: list[str] = []
    for shot in ir.shots:
        for line in shot.dialogues:
            emotion = f"（情绪：{line.emotion}）" if line.emotion else ""
            lines.append(
                f"[Shot {shot.index}] {line.speaker_name} ({line.speaker_id}){emotion}：{line.text}"
            )
    return "\n".join(lines) or "（本镜头没有台词）"


def _shot_block(ir: IRPrompt) -> str:
    blocks: list[str] = []
    for shot in ir.shots:
        blocks.append(
            "\n".join(
                [
                    f"[Shot {shot.index}] start={shot.start_seconds:g}s",
                    f"shot_size={shot.shot_size or '-'} angle={shot.camera_angle or '-'} "
                    f"movement={shot.camera_movement or '-'}",
                    f"location={shot.location or '-'}",
                    f"visual={shot.visual or '-'}",
                    "action_beats=" + (" / ".join(shot.action_beats) or "-"),
                    f"atmosphere={shot.atmosphere or '-'}",
                    f"composition_anchor={shot.composition_anchor or '-'}",
                    f"screen_direction={shot.screen_direction or '-'}",
                    f"continuity={shot.continuity or '-'}",
                ]
            )
        )
    return "\n\n".join(blocks) or "-"


def _rules_block(ir: IRPrompt) -> str:
    del ir
    return "\n".join(
        [
            "【竖屏构图】",
            rules.summarize_rules(rules.VERTICAL_FRAME_RULES),
            "【情绪写行为】",
            rules.summarize_rules(rules.EMOTION_AS_BEHAVIOR_RULES),
            "【短剧节奏】",
            rules.summarize_rules(rules.PACING_RULES),
            "【负面约束写法】",
            rules.summarize_rules(rules.NEGATIVE_PROMPT_DISCIPLINE),
        ]
    )


def build_h3_agent_variables(ir: IRPrompt) -> dict[str, str]:
    """把 IR 整理成 Agent 提示词变量（纯函数）。"""
    return {
        "duration_seconds": f"{ir.duration_seconds:g}",
        "aspect_ratio": ir.aspect_ratio or "9:16",
        "genre": ir.genre or "-",
        "visual_style": ir.visual_style or "-",
        "reference_block": _reference_block(ir),
        "subject_block": _subject_block(ir),
        "dialogue_block": _dialogue_block(ir),
        "shot_block": _shot_block(ir),
        "rules_block": _rules_block(ir),
        "banned_block": "、".join(rules.BANNED_ABSTRACT_WORDS) or "-",
    }


class H3VideoPromptAgent(AgentBase[H3Prose]):
    """把分镜 IR 写成 H3 官方英文六段正文。"""

    @property
    def output_model(self) -> type[H3Prose]:
        return H3Prose

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return PromptTemplate.from_template(_USER_TEMPLATE)

    def render_from_ir(self, ir: IRPrompt) -> str:
        """按 IR 渲染完整提示词（便于预览与排障）。"""
        return self.render_prompt(**build_h3_agent_variables(ir))


async def generate_h3_prose(
    llm: BaseChatModel,
    ir: IRPrompt,
) -> tuple[H3Prose | None, list[str]]:
    """调用 LLM 生成 H3 正文；失败时返回 (None, 警告)，由渲染器回落到结构骨架。"""
    agent = H3VideoPromptAgent(llm)
    try:
        prose = await agent.aextract(**build_h3_agent_variables(ir))
    except Exception as exc:  # noqa: BLE001 - 任何失败都应降级为骨架，不阻断生成链路
        return None, [f"H3 英文正文生成失败，已回落到结构骨架：{exc}"]
    if not isinstance(prose, H3Prose) or not prose.detailed_description.strip():
        return None, ["H3 英文正文为空，已回落到结构骨架"]
    return prose, []


__all__ = [
    "H3VideoPromptAgent",
    "build_h3_agent_variables",
    "generate_h3_prose",
]
