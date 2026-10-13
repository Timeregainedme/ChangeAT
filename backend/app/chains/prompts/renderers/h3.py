"""MiniMax H3 官方提示词格式渲染器。

依据 H3 官方提示词规范（`h3-prompt-writing` skill，`references/ref-en.txt`）：

- **全参考模式**（有参考素材）用固定六段：
  `subject_definitions` → `summary` → `retention_analysis` → `detailed_description`
  → `overall_soundscape` → `non_diegetic_music`；
- **基础模式**（无参考素材）用三段：
  `integrated_multimodal_description` → `overall_soundscape` → `non_diegetic_music`；
- 正文为英文；仅 `<d>` 内的台词/歌词与画面可见文字保留原语言；
- 参考模式要求先在 `[Shot 1]` 之前用 1–2 句英文确立风格；
- `[Shot 1]` 不带时间戳，后续镜头写 `[Shot N] At MM:SS.mmm, ...`；
- 说话人用稳定 `(S1)`/`(S2)`；台词写 `<d>[Language] ...</d>`；
- 段落名逐字保留英文，本项目其它文字可以是中文（骨架降级模式）。

渲染器是**确定性拼装 + 校验**：正文英文由上游 LLM 提供（`H3Prose`），
未提供时输出结构化骨架并给出警告，便于预览与排障。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from app.chains.prompts.ir import IRPrompt, IRShot

# 与优云智算 ModelVerse H3 通道一致的上限（`MAX_PROMPT_CHARS`）。
H3_MAX_PROMPT_CHARS = 7000
# 生成类任务的建议英文词数区间。
H3_RECOMMENDED_WORD_RANGE = (350, 500)

REFERENCE_SECTION_ORDER: tuple[str, ...] = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)

BASE_SECTION_ORDER: tuple[str, ...] = (
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
)

KNOWN_TASK_TYPES: tuple[str, ...] = (
    "keyframe completion",
    "reference generation",
    "video editing",
    "video continuation",
    "audio reuse",
    "audio reference",
)

# 可见内容保留标记。
VISIBLE_RETENTION_MARKERS: tuple[str, ...] = (
    "fully_preserved",
    "partially_preserved",
    "attribute_transfer",
    "weak_reference",
)

# 音频保留标记。
AUDIO_RETENTION_MARKERS: tuple[str, ...] = (
    "fully_copy",
    "partially_copy",
    "reference",
    "weak_reference",
)

_TIMESTAMP_PATTERN = re.compile(r"At (\d{2,}:\d{2}\.\d{3})")
_LABEL_DEFINITION_PATTERN = re.compile(r"^<(Subject|Picture|Video|Audio) (\d+)>:", re.MULTILINE)
_LABEL_USAGE_PATTERN = re.compile(r"<(Subject|Picture|Video|Audio) (\d+)>")


class H3Prose(BaseModel):
    """由上游 LLM 提供的英文正文分段落。

    每个字段对应 H3 的一个段落正文（不含段落名本身）。为空时该段落回落到结构化骨架。
    """

    model_config = ConfigDict(extra="forbid")

    subject_definitions: str = Field("", description="subject_definitions 段落正文")
    summary: str = Field("", description="summary 段落正文")
    retention_analysis: str = Field("", description="retention_analysis 段落正文")
    detailed_description: str = Field("", description="detailed_description 段落正文")
    overall_soundscape: str = Field("", description="overall_soundscape 段落正文")
    non_diegetic_music: str = Field("", description="non_diegetic_music 段落正文")
    integrated_multimodal_description: str = Field("", description="基础模式主段落正文")


@dataclass
class H3RenderResult:
    """渲染结果。"""

    text: str
    warnings: list[str] = field(default_factory=list)
    char_count: int = 0
    word_count: int = 0


def format_timestamp(seconds: float) -> str:
    """把秒数格式化为 H3 要求的 `MM:SS.mmm`（超过 59 分钟时分钟位自然增长）。"""
    total_ms = int(round(max(0.0, float(seconds or 0.0)) * 1000))
    minutes, remainder = divmod(total_ms, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def _parse_timestamp(value: str) -> float:
    minutes, rest = value.split(":")
    secs, millis = rest.split(".")
    return int(minutes) * 60 + int(secs) + int(millis) / 1000.0


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _count_words(text: str) -> int:
    return len([token for token in str(text or "").split() if token.strip()])


def _section_body(text: str, name: str) -> str:
    """取出 `name:` 所在段落的正文（截到下一个段落名之前）。"""
    marker = f"{name}:"
    start = str(text or "").find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = len(text)
    for other in REFERENCE_SECTION_ORDER + BASE_SECTION_ORDER:
        if other == name:
            continue
        position = text.find(f"{other}:", start)
        if position >= 0:
            end = min(end, position)
    return text[start:end]


def h3_label_for(kind: str, subject_index: int, picture_index: int) -> str:
    """把内部参考类型映射为 H3 标签。

    参考素材用于**定义内容单元**（角色/场景/道具/服装/风格）时用 `<Subject N>`；
    只有作为**具体目标帧或分镜锚点**时才用 `<Picture N>`。
    """
    if str(kind or "") == "frame":
        return f"<Picture {picture_index}>"
    return f"<Subject {subject_index}>"


# --------------------------------------------------------------------------- #
# 骨架回落（无 LLM 英文正文时）
# --------------------------------------------------------------------------- #


def _style_sentence(ir: IRPrompt) -> str:
    bits: list[str] = []
    if ir.style_anchor:
        bits.append(f"The video keeps the established project look: {ir.style_anchor}.")
    if ir.aspect_ratio:
        bits.append(f"The frame is composed for vertical delivery at {ir.aspect_ratio}.")
    if ir.duration_seconds:
        bits.append(f"Total duration is {ir.duration_seconds:g} seconds.")
    bits.append(
        "Subject identity, wardrobe, spatial layout, and lighting direction stay consistent "
        "with the supplied references throughout the shot."
    )
    return " ".join(bits)


def _subject_label_for_speaker(ir: IRPrompt, speaker_id: str) -> str:
    for subject in ir.subjects:
        if subject.speaker_id and subject.speaker_id == speaker_id:
            return subject.label
    return ""


def _dialogue_fragment(ir: IRPrompt, line) -> str:
    label = _subject_label_for_speaker(ir, line.speaker_id)
    who = f"<{label}> ({line.speaker_id})" if label else f"({line.speaker_id})"
    language = line.language or "Chinese"
    return f"{who} says, <d>[{language}] {line.text}</d>"


def _token_to_picture_label(token: str) -> str:
    """把内部参考 token（`图1`）转成 H3 的图片标签（`<Picture 1>`）。

    H3 规范：`<Picture N>` 只标识来源、不单独成行时，就写在该 `<Subject N>` 的定义行里。
    """
    match = re.search(r"(\d+)", str(token or ""))
    return f"<Picture {match.group(1)}>" if match else str(token or "").strip()


def _fallback_subject_definitions(ir: IRPrompt) -> str:
    lines: list[str] = []
    for subject in ir.subjects:
        text = f"<{subject.label}>: {subject.name}".rstrip()
        definition = str(subject.definition or "").strip()
        if definition:
            text = f"{text}, {definition}"
        if subject.source_tokens:
            sources = ", ".join(_token_to_picture_label(token) for token in subject.source_tokens)
            text = f"{text} (source: {sources})"
        lines.append(text.rstrip("。.") + ".")
    if not lines:
        return "N/A"
    return "\n".join(lines)


def _fallback_summary(ir: IRPrompt) -> str:
    prefix = " + ".join([t for t in ir.task_types if t in KNOWN_TASK_TYPES]) or "reference generation"
    shot = ir.shots[0] if ir.shots else None
    what = str(getattr(shot, "visual", "") or "").strip().rstrip("。.") or "the target shot"
    return f"[{prefix}] The target video shows {what}."


def _fallback_retention_analysis(ir: IRPrompt) -> str:
    lines: list[str] = []
    for subject in ir.subjects:
        appears = ", ".join(f"[Shot {index}]" for index in (subject.appears_in or [1]))
        marker = subject.retention if subject.retention in VISIBLE_RETENTION_MARKERS else "fully_preserved"
        source = _token_to_picture_label(subject.source_tokens[0]) if subject.source_tokens else ""
        suffix = f" from {source}" if source else ""
        lines.append(
            f"<{subject.label}> (appears in {appears}): {marker} - "
            f"the referenced {subject.kind} is reused as the source of this content unit{suffix}."
        )
    return "\n".join(lines) if lines else "N/A"


def _fallback_shot_block(ir: IRPrompt, shot: IRShot) -> str:
    if shot.index > 1 and shot.start_seconds > 0:
        header = f"[Shot {shot.index}] At {format_timestamp(shot.start_seconds)},"
    else:
        header = f"[Shot {shot.index}]"

    parts: list[str] = []
    if shot.visual:
        parts.append(str(shot.visual).strip())
    camera_bits = [bit for bit in (shot.shot_size, shot.camera_angle, shot.camera_movement) if bit]
    if camera_bits:
        parts.append(f"Shot size {shot.shot_size or 'unspecified'}, angle {shot.camera_angle or 'unspecified'}, camera {shot.camera_movement or 'static'}.")
    if shot.action_beats:
        parts.append("Action beats: " + "; ".join(shot.action_beats) + ".")
    if shot.atmosphere:
        parts.append(f"Atmosphere: {shot.atmosphere}.")
    if shot.composition_anchor:
        parts.append(f"Framing: {shot.composition_anchor}.")
    if shot.screen_direction:
        parts.append(f"Screen direction: {shot.screen_direction}.")
    for line in shot.dialogues:
        parts.append(_dialogue_fragment(ir, line))
    if shot.sound:
        parts.append(f"Sound: {shot.sound}.")
    if shot.continuity:
        parts.append(f"Continuity: {shot.continuity}.")

    body = " ".join(part for part in parts if part).strip()
    return f"{header} {body}".strip() if body else header


def _fallback_detailed_description(ir: IRPrompt) -> str:
    blocks: list[str] = [_style_sentence(ir)]
    for shot in ir.shots:
        blocks.append(_fallback_shot_block(ir, shot))
    if not ir.shots:
        blocks.append("[Shot 1]")
    return "\n".join(block for block in blocks if str(block).strip())


def _fallback_soundscape(ir: IRPrompt) -> str:
    for shot in ir.shots:
        if str(shot.sound or "").strip():
            return str(shot.sound).strip()
    return "Room tone and natural physical sounds continue throughout the video."


def _fallback_music() -> str:
    return "N/A"


def _fallback_multimodal(ir: IRPrompt) -> str:
    return _fallback_detailed_description(ir)


_FALLBACK_BUILDERS = {
    "subject_definitions": _fallback_subject_definitions,
    "summary": _fallback_summary,
    "retention_analysis": _fallback_retention_analysis,
    "detailed_description": _fallback_detailed_description,
    "overall_soundscape": _fallback_soundscape,
    "non_diegetic_music": lambda _ir: _fallback_music(),
    "integrated_multimodal_description": _fallback_multimodal,
}


def _resolve_section(name: str, ir: IRPrompt, prose: H3Prose | None) -> str:
    if prose is not None:
        value = str(getattr(prose, name, "") or "").strip()
        if value:
            return value
    builder = _FALLBACK_BUILDERS.get(name)
    return builder(ir) if builder else ""


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #


def render_h3_reference(
    ir: IRPrompt,
    *,
    prose: H3Prose | None = None,
    max_chars: int = H3_MAX_PROMPT_CHARS,
) -> H3RenderResult:
    """按 H3 全参考模式渲染六段式提示词。"""
    warnings: list[str] = []
    if prose is None or not any(
        str(getattr(prose, name, "") or "").strip() for name in REFERENCE_SECTION_ORDER
    ):
        warnings.append("未提供英文正文（H3Prose），已输出结构化骨架：结构与标签合规，但正文语言与 IR 一致")

    sections: list[str] = []
    for name in REFERENCE_SECTION_ORDER:
        body = _resolve_section(name, ir, prose).strip() or "N/A"
        sections.append(f"{name}:\n{body}")
    text = "\n\n".join(sections).strip()

    warnings.extend(
        validate_h3_reference(text, duration_seconds=ir.duration_seconds, max_chars=max_chars)
    )
    return H3RenderResult(
        text=text,
        warnings=_dedupe(warnings),
        char_count=len(text),
        word_count=_count_words(text),
    )


def render_h3_base(
    ir: IRPrompt,
    *,
    prose: H3Prose | None = None,
    max_chars: int = H3_MAX_PROMPT_CHARS,
) -> H3RenderResult:
    """按 H3 基础模式渲染三段式提示词（无参考素材时使用）。"""
    warnings: list[str] = []
    if prose is None or not str(getattr(prose, "integrated_multimodal_description", "") or "").strip():
        warnings.append("未提供英文正文（H3Prose），已输出结构化骨架：结构与标签合规，但正文语言与 IR 一致")

    sections: list[str] = []
    for name in BASE_SECTION_ORDER:
        body = _resolve_section(name, ir, prose).strip() or "N/A"
        sections.append(f"{name}:\n{body}")
    text = "\n\n".join(sections).strip()

    if len(text) > max_chars:
        warnings.append(f"提示词长度 {len(text)} 超过 H3 上限 {max_chars} 字符")
    d_open, d_close = text.count("<d>"), text.count("</d>")
    if d_open != d_close:
        warnings.append(f"<d> 台词标签未成对闭合（{d_open} 开 / {d_close} 闭）")

    return H3RenderResult(
        text=text,
        warnings=_dedupe(warnings),
        char_count=len(text),
        word_count=_count_words(text),
    )


def render_h3(
    ir: IRPrompt,
    *,
    prose: H3Prose | None = None,
    max_chars: int = H3_MAX_PROMPT_CHARS,
) -> H3RenderResult:
    """按是否存在参考素材自动选择 H3 参考模式或基础模式。"""
    if ir.references or ir.subjects:
        return render_h3_reference(ir, prose=prose, max_chars=max_chars)
    return render_h3_base(ir, prose=prose, max_chars=max_chars)


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #


def validate_h3_reference(
    text: str,
    *,
    duration_seconds: float | None = None,
    max_chars: int = H3_MAX_PROMPT_CHARS,
) -> list[str]:
    """校验参考模式提示词的结构合规性，返回问题列表（空表示通过）。"""
    warnings: list[str] = []
    body = str(text or "")

    missing = [name for name in REFERENCE_SECTION_ORDER if f"{name}:" not in body]
    if missing:
        warnings.append("缺少 H3 必需段落：" + "、".join(missing))

    positions = [body.find(f"{name}:") for name in REFERENCE_SECTION_ORDER]
    present = [position for position in positions if position >= 0]
    if present != sorted(present):
        warnings.append("H3 段落顺序不符合规范（应为 " + " → ".join(REFERENCE_SECTION_ORDER) + "）")

    # retention_analysis 里也会合法出现 `([Shot 1])`，所以镜头锚点必须在
    # detailed_description 这一段内部查找，不能全文搜索。
    description_body = _section_body(body, "detailed_description")

    if "[Shot 1]" not in description_body:
        warnings.append("detailed_description 缺少 [Shot 1]")

    shot_one = description_body.find("[Shot 1]")
    if shot_one >= 0 and not description_body[:shot_one].strip():
        warnings.append("参考模式要求在 [Shot 1] 之前先用 1–2 句英文确立风格")

    if re.search(r"\[Shot 1\]\s*At ", description_body):
        warnings.append("[Shot 1] 不应带时间戳（首个镜头不写 At MM:SS.mmm）")

    d_open, d_close = body.count("<d>"), body.count("</d>")
    if d_open != d_close:
        warnings.append(f"<d> 台词标签未成对闭合（{d_open} 开 / {d_close} 闭）")

    # 只有 <Subject N> 必须单行定义；<Picture N>/<Video N>/<Audio N> 按规范写在各定义行内。
    defined_subjects = {
        number for kind, number in _LABEL_DEFINITION_PATTERN.findall(body) if kind == "Subject"
    }
    used_subjects = {
        number for kind, number in _LABEL_USAGE_PATTERN.findall(body) if kind == "Subject"
    }
    undefined = used_subjects - defined_subjects
    if undefined:
        warnings.append(
            "使用了未在 subject_definitions 单行定义的 <Subject N>："
            + "、".join(f"<Subject {number}>" for number in sorted(undefined))
        )

    stamps = [_parse_timestamp(value) for value in _TIMESTAMP_PATTERN.findall(body)]
    if stamps:
        last = max(stamps)
        if last > 0 and not 4.0 <= last <= 15.0 + 0.001:
            warnings.append(f"最后一个切点 {format_timestamp(last)} 落在 H3 建议的单段 4–15 秒之外")
        if duration_seconds and last > float(duration_seconds) + 0.001:
            warnings.append(
                f"时间轴最后切点 {format_timestamp(last)} 超出镜头时长 {float(duration_seconds):g} 秒"
            )

    if len(body) > max_chars:
        warnings.append(f"提示词长度 {len(body)} 超过 H3 上限 {max_chars} 字符")

    # H3 的 350–500 词建议针对常规生成任务；5–8 秒的短剧单镜头达不到该体量，
    # 仅在明显偏长的镜头上提示，避免制造噪音。
    words = _count_words(body)
    low, high = H3_RECOMMENDED_WORD_RANGE
    if 0 < words < low and (duration_seconds or 0) >= 8.0:
        warnings.append(f"英文正文 {words} 词，低于 H3 生成类任务建议的 {low}–{high} 词区间")

    return _dedupe(warnings)


__all__ = [
    "AUDIO_RETENTION_MARKERS",
    "BASE_SECTION_ORDER",
    "H3_MAX_PROMPT_CHARS",
    "H3Prose",
    "H3_RECOMMENDED_WORD_RANGE",
    "H3RenderResult",
    "KNOWN_TASK_TYPES",
    "REFERENCE_SECTION_ORDER",
    "VISIBLE_RETENTION_MARKERS",
    "format_timestamp",
    "h3_label_for",
    "render_h3",
    "render_h3_base",
    "render_h3_reference",
    "validate_h3_reference",
]
