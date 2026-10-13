"""镜头视频提示词上下文包与模板渲染底层服务。

该模块只负责两类稳定能力：

1. 构建 `ShotVideoPromptPackRead`
2. 基于模板将 pack 渲染为文本

视频预览与提交编排统一放在 `app.services.studio.generation.video`。
"""

from __future__ import annotations

from typing import Any
import re

from fastapi import HTTPException, status
from langchain_core.prompts import PromptTemplate as LcPromptTemplate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.studio import Chapter, PromptCategory, PromptTemplate, Shot, ShotDetail
from app.schemas.studio.shots import (
    ActionBeatPhaseRead,
    ShotPromptAssetRef,
    ShotPromptCameraInfo,
    ShotVideoPromptPackRead,
)
from app.services.common import entity_not_found
from app.services.studio.action_beats import infer_action_beat_sequence
from app.services.studio.shot_assets_overview import get_shot_assets_overview


DEFAULT_VIDEO_NEGATIVE_PROMPT = (
    "不要新增无关人物；不要改变角色身份、服装颜色和场景地点；"
    "不要出现文字水印、肢体畸形、镜头跳变和画面闪烁。"
)


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return str(raw or "")


def _asset_ref_from_overview_item(item: Any) -> ShotPromptAssetRef:
    return ShotPromptAssetRef(
        type=item.type,
        name=item.name,
        description=item.description or "",
        file_id=item.file_id,
        thumbnail=item.thumbnail,
    )


def _pack_variables(pack: ShotVideoPromptPackRead) -> dict[str, Any]:
    """为 DB 模板暴露稳定变量名。

    同时保留扁平变量和 `pack`，让模板可以逐步迁移到更结构化的写法。
    """
    data = pack.model_dump()
    return {
        "pack": data,
        "shot_id": pack.shot_id,
        "shot_title": pack.title,
        "title": pack.title,
        "script_excerpt": pack.script_excerpt,
        "action_beats": "\n".join(pack.action_beats),
        "action_beats_text": "；".join(pack.action_beats),
        "previous_shot_summary": pack.previous_shot_summary,
        "next_shot_goal": pack.next_shot_goal,
        "continuity_guidance": pack.continuity_guidance,
        "composition_anchor": pack.composition_anchor,
        "screen_direction_guidance": pack.screen_direction_guidance,
        "dialogue_summary": pack.dialogue_summary,
        "characters": pack.characters,
        "character_names": "、".join(item.name for item in pack.characters),
        "scene": pack.scene,
        "scene_name": pack.scene.name if pack.scene else "",
        "props": pack.props,
        "prop_names": "、".join(item.name for item in pack.props),
        "costumes": pack.costumes,
        "costume_names": "、".join(item.name for item in pack.costumes),
        "camera": pack.camera,
        "camera_shot": pack.camera.camera_shot,
        "angle": pack.camera.angle,
        "movement": pack.camera.movement,
        "duration": pack.camera.duration or "",
        "atmosphere": pack.atmosphere,
        "visual_style": pack.visual_style,
        "style": pack.style,
        "negative_prompt": pack.negative_prompt,
    }


def _render_template(content: str, variables: dict[str, Any]) -> str:
    template = LcPromptTemplate.from_template(template=content, template_format="jinja2")
    render_vars = {name: variables.get(name, "") for name in template.input_variables}
    return template.format(**render_vars).strip()


def _build_guidance_suffix(pack: ShotVideoPromptPackRead) -> str:
    """生成一段稳定的镜头执行约束，供模板渲染结果补强使用。"""
    lines: list[str] = []
    if pack.action_beats:
        lines.append(f"动作节拍：{'；'.join(pack.action_beats)}")
    if pack.previous_shot_summary:
        lines.append(f"上一镜头承接：{pack.previous_shot_summary}")
    if pack.next_shot_goal:
        lines.append(f"下一镜头目标：{pack.next_shot_goal}")
    if pack.continuity_guidance:
        lines.append(f"连续性要求：{pack.continuity_guidance}")
    if pack.composition_anchor:
        lines.append(f"构图锚点：{pack.composition_anchor}")
    if pack.screen_direction_guidance:
        lines.append(f"朝向与视线：{pack.screen_direction_guidance}")
    return "\n".join(lines).strip()


def enrich_rendered_video_prompt(
    *,
    rendered_prompt: str,
    pack: ShotVideoPromptPackRead,
) -> str:
    """为模板渲染结果补强关键执行约束。

    若模板未显式消费新的连续性/构图变量，则自动在末尾追加一段稳定约束，
    避免这类信息只停留在 preview pack 中却没有真正进入最终 prompt。
    """
    text = str(rendered_prompt or "").strip()
    suffix = _build_guidance_suffix(pack)
    if not suffix:
        return text

    normalized = text.replace(" ", "")
    if any(
        marker in normalized
        for marker in (
            "动作节拍：",
            "上一镜头承接：",
            "连续性要求：",
            "构图锚点：",
            "朝向与视线：",
        )
    ):
        return text

    if not text:
        return suffix
    return f"{text}\n\n{suffix}".strip()


def _split_beats(*values: str) -> list[str]:
    """按常见中文断句规则拆分为动作节拍候选。"""
    parts: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        for piece in re.split(r"[。！？；\n]+", text):
            item = piece.strip("，,、 ").strip()
            if len(item) >= 4:
                parts.append(item)
    return parts


def _dedupe_keep_order(items: list[str], *, limit: int = 4) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _build_action_beats(
    *,
    confirmed_action_beats: list[str] | None,
    script_excerpt: str,
    shot_description: str,
    dialogue_summary: str,
) -> list[str]:
    """从剧本摘录、镜头描述与对白中提炼镜头内动作节拍。"""
    confirmed = _dedupe_keep_order(list(confirmed_action_beats or []), limit=4)
    if confirmed:
        return confirmed
    beat_candidates = _split_beats(shot_description, script_excerpt)
    dialogue_candidates = [
        f"对白推进：{item}"
        for item in _split_beats(dialogue_summary)
        if len(item) <= 24
    ]
    return _dedupe_keep_order(beat_candidates + dialogue_candidates, limit=4)


def _build_neighbor_prompt_summary(shot: Shot | None) -> tuple[str, str]:
    """生成相邻镜头摘要与承接目标。"""
    if shot is None:
        return "", ""
    detail = getattr(shot, "detail", None)
    scene_name = str(getattr(getattr(detail, "scene", None), "name", "") or "").strip()
    shot_description = str(getattr(detail, "description", "") or "").strip()
    camera_parts = [
        _enum_value(getattr(detail, "camera_shot", None)),
        _enum_value(getattr(detail, "angle", None)),
        _enum_value(getattr(detail, "movement", None)),
    ]
    summary_parts = [
        f"标题：{str(shot.title or '').strip()}" if str(shot.title or '').strip() else "",
        f"场景：{scene_name}" if scene_name else "",
        f"镜头语言：{' / '.join(part for part in camera_parts if part)}" if any(camera_parts) else "",
        f"画面状态：{shot_description}" if shot_description else "",
        f"剧本摘录：{str(shot.script_excerpt or '').strip()}" if str(shot.script_excerpt or '').strip() else "",
    ]
    compact = "；".join(part for part in summary_parts if part)
    goal_parts = [
        f"标题：{str(shot.title or '').strip()}" if str(shot.title or '').strip() else "",
        shot_description or str(shot.script_excerpt or "").strip(),
    ]
    goal = "；".join(part for part in goal_parts if part)
    return compact, goal


def _build_continuity_guidance(
    *,
    current_shot: Shot,
    previous_shot: Shot | None,
    next_shot: Shot | None,
) -> str:
    """构造视频提示词的连续性建议。"""
    detail = getattr(current_shot, "detail", None)
    current_scene_id = str(getattr(detail, "scene_id", "") or "")
    tips: list[str] = []
    if previous_shot is not None:
        tips.append("承接上一镜头的动作、视线或情绪，不要像新场景重新开局")
        previous_detail = getattr(previous_shot, "detail", None)
        previous_scene_id = str(getattr(previous_detail, "scene_id", "") or "")
        if current_scene_id and previous_scene_id and current_scene_id == previous_scene_id:
            tips.append("与上一镜头同场景时保持空间轴线和人物朝向稳定")
    if next_shot is not None:
        tips.append("在本镜头结尾形成自然收束，为下一镜头留出动作或情绪落点")
        next_detail = getattr(next_shot, "detail", None)
        next_scene_id = str(getattr(next_detail, "scene_id", "") or "")
        if current_scene_id and next_scene_id and current_scene_id == next_scene_id:
            tips.append("与下一镜头同场景时保持视觉重心连续，避免突兀跳轴")
    return "；".join(tips)


def _build_composition_anchor(
    *,
    shot: Shot,
    previous_shot: Shot | None,
    next_shot: Shot | None,
    scene_name: str,
    character_names: list[str],
) -> str:
    """为视频提示词构造稳定的画面构图与空间锚点建议。"""
    detail = getattr(shot, "detail", None)
    camera_shot = _enum_value(getattr(detail, "camera_shot", None))
    movement = _enum_value(getattr(detail, "movement", None))
    anchors: list[str] = []

    if camera_shot in {"ECU", "CU"}:
        anchors.append("以人物表情或关键动作细节作为画面重心，环境只保留必要轮廓")
    elif camera_shot in {"MS", "FS"}:
        anchors.append("保持人物与环境的相对位置可读，避免主体漂在空场中")
    else:
        anchors.append("先建立环境纵深和主体站位，再推进动作表现")

    if movement in {"DOLLY_IN", "ZOOM_IN"}:
        anchors.append("镜头重心应逐步向主体收束，形成推进感")
    elif movement in {"DOLLY_OUT", "ZOOM_OUT"}:
        anchors.append("镜头重心可从主体退向环境，强调空间扩展")
    elif movement == "STATIC":
        anchors.append("保持主体在画面中的位置稳定，避免重心突然跳变")

    if scene_name:
        anchors.append(f"以场景 {scene_name} 作为主要空间锚点")
    if character_names:
        anchors.append(f"锁定角色 {'、'.join(character_names[:2])} 的朝向与视线逻辑")

    current_scene_id = str(getattr(detail, "scene_id", "") or "")
    previous_scene_id = str(getattr(getattr(previous_shot, "detail", None), "scene_id", "") or "")
    next_scene_id = str(getattr(getattr(next_shot, "detail", None), "scene_id", "") or "")
    if previous_shot is not None and current_scene_id and current_scene_id == previous_scene_id:
        anchors.append("与上一镜头同场景时，延续既有空间轴线和视觉方向")
    if next_shot is not None and current_scene_id and current_scene_id == next_scene_id:
        anchors.append("与下一镜头同场景时，保留可自然衔接的视觉落点")

    return "；".join(anchors)


def _build_screen_direction_guidance(
    *,
    shot: Shot,
    previous_shot: Shot | None,
    next_shot: Shot | None,
    dialogue_summary: str,
    character_names: list[str],
) -> str:
    """构造视频镜头的人物朝向、视线与左右轴线建议。"""
    detail = getattr(shot, "detail", None)
    angle = _enum_value(getattr(detail, "angle", None))
    guidance: list[str] = []

    if angle == "OVER_SHOULDER":
        guidance.append("保持过肩镜头的前景肩部位置稳定，不要无故交换左右关系")
    elif angle == "EYE_LEVEL":
        guidance.append("保持人物平视方向和视线落点连续，避免镜头间突然翻面")
    else:
        guidance.append("明确人物朝向与视线落点，避免跳轴和朝向突变")

    if dialogue_summary.strip():
        guidance.append("对白驱动镜头应优先保持说话者与受话者的对视逻辑")
    if len(character_names) >= 2:
        guidance.append(f"角色 {character_names[0]} 与 {character_names[1]} 的左右站位和对视方向应保持稳定")
    elif character_names:
        guidance.append(f"角色 {character_names[0]} 的视线方向应在相邻镜头中保持延续")

    current_scene_id = str(getattr(detail, "scene_id", "") or "")
    previous_scene_id = str(getattr(getattr(previous_shot, "detail", None), "scene_id", "") or "")
    next_scene_id = str(getattr(getattr(next_shot, "detail", None), "scene_id", "") or "")
    if previous_shot is not None and current_scene_id and current_scene_id == previous_scene_id:
        guidance.append("与上一镜头同场景时，不要无故翻转人物左右面向")
    if next_shot is not None and current_scene_id and current_scene_id == next_scene_id:
        guidance.append("与下一镜头同场景时，为后续镜头保留可延续的视线方向")

    return "；".join(guidance)


def _fallback_video_prompt(pack: ShotVideoPromptPackRead) -> str:
    style_text = "，".join(x for x in [pack.visual_style, pack.style] if x)
    camera_text = " / ".join(x for x in [pack.camera.camera_shot, pack.camera.angle, pack.camera.movement] if x)
    parts = [
        f"镜头标题：{pack.title}",
        f"剧本摘录：{pack.script_excerpt}",
        f"动作节拍：{'；'.join(pack.action_beats)}" if pack.action_beats else "",
        f"画面风格：{style_text}",
        f"镜头语言：{camera_text}",
        f"时长：{pack.camera.duration} 秒" if pack.camera.duration else "",
        f"场景：{pack.scene.name if pack.scene else ''}",
        f"角色：{'、'.join(item.name for item in pack.characters)}",
        f"道具：{'、'.join(item.name for item in pack.props)}",
        f"服装：{'、'.join(item.name for item in pack.costumes)}",
        f"对白摘要：{pack.dialogue_summary}",
        f"上一镜头：{pack.previous_shot_summary}" if pack.previous_shot_summary else "",
        f"下一镜头目标：{pack.next_shot_goal}" if pack.next_shot_goal else "",
        f"连续性要求：{pack.continuity_guidance}" if pack.continuity_guidance else "",
        f"构图锚点：{pack.composition_anchor}" if pack.composition_anchor else "",
        f"朝向与视线：{pack.screen_direction_guidance}" if pack.screen_direction_guidance else "",
        f"氛围：{pack.atmosphere}",
        f"负面约束：{pack.negative_prompt}",
    ]
    return "\n".join(part for part in parts if part.split("：", 1)[-1].strip())


async def _resolve_video_prompt_template(
    db: AsyncSession,
    *,
    template_id: str | None,
) -> PromptTemplate | None:
    if template_id:
        template = await db.get(PromptTemplate, template_id)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("PromptTemplate"))
        if template.category != PromptCategory.video_prompt:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PromptTemplate is not video_prompt category")
        return template

    stmt = (
        select(PromptTemplate)
        .where(PromptTemplate.category == PromptCategory.video_prompt)
        .order_by(PromptTemplate.is_default.desc(), PromptTemplate.updated_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def build_shot_video_prompt_pack(
    db: AsyncSession,
    *,
    shot_id: str,
) -> ShotVideoPromptPackRead:
    stmt = (
        select(Shot)
        .options(
            selectinload(Shot.detail).selectinload(ShotDetail.dialog_lines),
            selectinload(Shot.chapter).selectinload(Chapter.project),
        )
        .where(Shot.id == shot_id)
    )
    shot = (await db.execute(stmt)).scalar_one_or_none()
    if shot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("Shot"))

    detail = shot.detail
    project = getattr(getattr(shot, "chapter", None), "project", None)
    overview = await get_shot_assets_overview(db, shot_id=shot_id)
    neighbors_stmt = (
        select(Shot)
        .options(selectinload(Shot.detail).selectinload(ShotDetail.scene))
        .where(
            Shot.chapter_id == shot.chapter_id,
            Shot.index.in_([shot.index - 1, shot.index + 1]),
        )
    )
    neighbor_rows = (await db.execute(neighbors_stmt)).scalars().all()
    previous_shot = next((item for item in neighbor_rows if item.index == shot.index - 1), None)
    next_shot = next((item for item in neighbor_rows if item.index == shot.index + 1), None)

    characters: list[ShotPromptAssetRef] = []
    props: list[ShotPromptAssetRef] = []
    costumes: list[ShotPromptAssetRef] = []
    scene: ShotPromptAssetRef | None = None
    for item in overview.items:
        if not item.is_linked:
            continue
        ref = _asset_ref_from_overview_item(item)
        if item.type == "character":
            characters.append(ref)
        elif item.type == "prop":
            props.append(ref)
        elif item.type == "costume":
            costumes.append(ref)
        elif item.type == "scene" and scene is None:
            scene = ref

    dialog_lines = list(getattr(detail, "dialog_lines", []) or []) if detail is not None else []
    dialogue_summary = "\n".join(
        f"{line.speaker_name or '角色'}：{line.text}" if line.speaker_name else line.text
        for line in sorted(dialog_lines, key=lambda x: (x.index, x.id))
        if line.text
    )
    previous_shot_summary, _ = _build_neighbor_prompt_summary(previous_shot)
    _, next_shot_goal = _build_neighbor_prompt_summary(next_shot)
    action_beats = _build_action_beats(
        confirmed_action_beats=list(getattr(detail, "action_beats", []) or []),
        script_excerpt=shot.script_excerpt or "",
        shot_description=str(getattr(detail, "description", "") or ""),
        dialogue_summary=dialogue_summary,
    )

    return ShotVideoPromptPackRead(
        shot_id=shot.id,
        title=shot.title or "",
        script_excerpt=shot.script_excerpt or "",
        shot_description=str(getattr(detail, "description", "") or ""),
        action_beats=action_beats,
        action_beat_phases=[
            ActionBeatPhaseRead(text=item.text, phase=item.phase)
            for item in infer_action_beat_sequence(action_beats)
        ],
        previous_shot_summary=previous_shot_summary,
        next_shot_goal=next_shot_goal,
        continuity_guidance=_build_continuity_guidance(
            current_shot=shot,
            previous_shot=previous_shot,
            next_shot=next_shot,
        ),
        composition_anchor=_build_composition_anchor(
            shot=shot,
            previous_shot=previous_shot,
            next_shot=next_shot,
            scene_name=scene.name if scene else "",
            character_names=[item.name for item in characters],
        ),
        screen_direction_guidance=_build_screen_direction_guidance(
            shot=shot,
            previous_shot=previous_shot,
            next_shot=next_shot,
            dialogue_summary=dialogue_summary,
            character_names=[item.name for item in characters],
        ),
        dialogue_summary=dialogue_summary,
        characters=characters,
        scene=scene,
        props=props,
        costumes=costumes,
        camera=ShotPromptCameraInfo(
            camera_shot=_enum_value(getattr(detail, "camera_shot", None)),
            angle=_enum_value(getattr(detail, "angle", None)),
            movement=_enum_value(getattr(detail, "movement", None)),
            duration=getattr(detail, "duration", None),
        ),
        atmosphere=str(getattr(detail, "atmosphere", "") or ""),
        visual_style=_enum_value(getattr(project, "visual_style", None)),
        style=_enum_value(getattr(project, "style", None)),
        negative_prompt=DEFAULT_VIDEO_NEGATIVE_PROMPT,
    )
