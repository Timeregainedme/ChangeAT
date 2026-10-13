from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.chains.agents import (
    ShotFirstFramePromptAgent,
    ShotKeyFramePromptAgent,
    ShotLastFramePromptAgent,
)
from app.chains.agents.shot_frame_prompt_agents import FRAME_CATEGORY_BY_TYPE
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.studio import (
    Chapter,
    Character,
    Costume,
    ProjectCostumeLink,
    ProjectPropLink,
    ProjectSceneLink,
    Prop,
    Scene,
    Shot,
    ShotCharacterLink,
    ShotDetail,
)
from app.models.types import PromptCategory
from app.services.llm.runtime import build_default_text_llm_sync
from app.services.common import entity_not_found, invalid_choice
from app.services.studio.action_beats import infer_action_beat_sequence, pick_action_beat_for_frame
from app.services.studio.image_tasks import resolve_prompt_template
from app.services.studio.shot_status import recompute_shot_status
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_logging import log_task_event, log_task_failure


def normalize_frame_type(frame_type: str) -> str:
    value = (frame_type or "").strip().lower()
    if value not in {"first", "last", "key"}:
        raise HTTPException(status_code=400, detail=invalid_choice("frame_type", ["first", "last", "key"]))
    return value


def relation_type_for_frame(frame_type: str) -> str:
    if frame_type == "first":
        return "shot_first_frame_prompt"
    if frame_type == "last":
        return "shot_last_frame_prompt"
    return "shot_key_frame_prompt"


async def resolve_frame_template_override(
    db: AsyncSession,
    *,
    frame_type: str,
) -> str | None:
    """读取后台（`prompt_templates`）配置的帧提示词模板内容（B1）。

    没有配置、内容为空或查库异常时返回 None，由 Agent 回退到内置模板，
    保证后台没配模板时链路照常可跑。
    """
    category = FRAME_CATEGORY_BY_TYPE.get(str(frame_type or "").strip().lower())
    if not category:
        return None
    try:
        template = await resolve_prompt_template(db, category=PromptCategory(category))
    except Exception:
        return None
    content = getattr(template, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    return None


def _enum_value(value: object | None) -> str:
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return str(raw or "")


def _compact_text(value: str | None) -> str:
    return str(value or "").strip()


def _join_context_lines(lines: list[str]) -> str:
    cleaned = [line for line in lines if line]
    return "\n".join(cleaned) if cleaned else "无"


def _build_character_context(characters: list[Character]) -> str:
    lines: list[str] = []
    for character in characters:
        fragments: list[str] = []
        if _compact_text(character.description):
            fragments.append(_compact_text(character.description))
        actor = getattr(character, "actor", None)
        if actor is not None and _compact_text(getattr(actor, "name", None)):
            actor_desc = f"演员形象：{_compact_text(getattr(actor, 'name', None))}"
            if _compact_text(getattr(actor, "description", None)):
                actor_desc += f"（{_compact_text(getattr(actor, 'description', None))}）"
            fragments.append(actor_desc)
        costume = getattr(character, "costume", None)
        if costume is not None and _compact_text(getattr(costume, "name", None)):
            costume_desc = f"默认服装：{_compact_text(getattr(costume, 'name', None))}"
            if _compact_text(getattr(costume, "description", None)):
                costume_desc += f"（{_compact_text(getattr(costume, 'description', None))}）"
            fragments.append(costume_desc)
        line = f"- {character.name}"
        if fragments:
            line += f"：{'；'.join(fragments)}"
        lines.append(line)
    return _join_context_lines(lines)


def _build_named_asset_context(assets: list[Scene] | list[Prop] | list[Costume]) -> str:
    lines: list[str] = []
    for asset in assets:
        line = f"- {asset.name}"
        if _compact_text(getattr(asset, "description", None)):
            line += f"：{_compact_text(getattr(asset, 'description', None))}"
        lines.append(line)
    return _join_context_lines(lines)


def _build_subject_priority(
    *,
    characters: list[Character],
    scenes: list[Scene],
    props: list[Prop],
    costumes: list[Costume],
) -> str:
    parts: list[str] = []
    if characters:
        primary_names = "、".join(character.name for character in characters[:2])
        parts.append(f"优先以角色 {primary_names} 作为画面主体")
        if len(characters) > 2:
            support_names = "、".join(character.name for character in characters[2:])
            parts.append(f"其余角色 {support_names} 仅在能强化画面关系时再补充")
    if scenes:
        parts.append(f"优先建立场景 {scenes[0].name} 的环境信息")
    if props:
        prop_names = "、".join(prop.name for prop in props[:2])
        parts.append(f"道具 {prop_names} 仅在进入主动作或构图焦点时重点写入")
    if costumes:
        costume_names = "、".join(costume.name for costume in costumes[:2])
        parts.append(f"服装 {costume_names} 主要用于强化人物外观一致性，不必喧宾夺主")
    return "；".join(parts) if parts else "优先根据镜头信息突出主角色和主场景，不必平均铺陈所有元素"


def _truncate_for_prompt(value: str | None, *, limit: int = 80) -> str:
    text = _compact_text(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _summarize_neighbor_shot(shot: Shot | None) -> tuple[str, str, str]:
    """生成相邻镜头的标题、摘录和状态摘要，供连续性提示词使用。"""
    if shot is None:
        return "", "", ""
    detail = getattr(shot, "detail", None)
    scene_name = _compact_text(getattr(getattr(detail, "scene", None), "name", None))
    camera_parts = [
        _enum_value(getattr(detail, "camera_shot", None)),
        _enum_value(getattr(detail, "angle", None)),
        _enum_value(getattr(detail, "movement", None)),
    ]
    camera_text = " / ".join(part for part in camera_parts if part)
    description = _truncate_for_prompt(getattr(detail, "description", None), limit=60)
    summary_parts = [
        f"场景：{scene_name}" if scene_name else "",
        f"镜头语言：{camera_text}" if camera_text else "",
        f"画面状态：{description}" if description else "",
    ]
    return (
        _compact_text(getattr(shot, "title", None)),
        _truncate_for_prompt(getattr(shot, "script_excerpt", None), limit=80),
        "；".join(part for part in summary_parts if part),
    )


def _build_continuity_guidance(
    *,
    previous_shot: Shot | None,
    current_shot: Shot,
    next_shot: Shot | None,
) -> str:
    """基于相邻镜头关系生成简明连续性约束。"""
    guidance: list[str] = []
    current_detail = getattr(current_shot, "detail", None)
    current_scene_id = str(getattr(current_detail, "scene_id", "") or "")
    previous_detail = getattr(previous_shot, "detail", None) if previous_shot else None
    next_detail = getattr(next_shot, "detail", None) if next_shot else None
    previous_scene_id = str(getattr(previous_detail, "scene_id", "") or "")
    next_scene_id = str(getattr(next_detail, "scene_id", "") or "")

    if previous_shot is not None:
        guidance.append("当前镜头应承接上一镜头的动作与情绪，不要像全新场面重新开局")
        if current_scene_id and previous_scene_id and current_scene_id == previous_scene_id:
            guidance.append("上一镜头与当前镜头处于同一场景，优先保持空间轴线和主体朝向稳定")
        if _enum_value(getattr(previous_detail, "movement", None)) and _enum_value(getattr(current_detail, "movement", None)):
            guidance.append("若镜头语言未明显变化，应视为同一动作链条中的推进或延续")

    if next_shot is not None:
        guidance.append("当前镜头应形成自然收束，为下一镜头预留动作或情绪落点，避免硬切")
        if current_scene_id and next_scene_id and current_scene_id == next_scene_id:
            guidance.append("下一镜头与当前镜头处于同一场景，尽量保持视觉重心与空间关系可连续延展")

    return "；".join(guidance)


def _build_composition_anchor(
    *,
    detail: ShotDetail,
    previous_shot: Shot | None,
    next_shot: Shot | None,
    characters: list[Character],
    scenes: list[Scene],
) -> str:
    """根据镜头语言和相邻镜头关系生成构图锚点建议。"""
    anchors: list[str] = []
    camera_shot = _enum_value(detail.camera_shot)
    movement = _enum_value(detail.movement)

    if camera_shot in {"ECU", "CU"}:
        anchors.append("以主角色面部或关键动作作为画面重心，弱化环境干扰")
    elif camera_shot in {"MS", "FS"}:
        anchors.append("保持人物与环境同时可读，避免只剩情绪特写或只剩空场")
    else:
        anchors.append("优先建立空间关系，再突出主角色动作")

    if movement in {"DOLLY_IN", "ZOOM_IN"}:
        anchors.append("构图应体现向主体推进的视觉趋势，焦点逐步收束到主角色")
    elif movement in {"DOLLY_OUT", "ZOOM_OUT"}:
        anchors.append("构图应体现从主体向环境退开的趋势，保留更多空间信息")
    elif movement == "STATIC":
        anchors.append("保持构图稳定，不要无故改变主体在画面中的重心位置")

    if scenes:
        anchors.append(f"以场景 {scenes[0].name} 作为空间锚点，保证主体与环境关系清晰")
    if characters:
        anchors.append(f"优先锁定角色 {characters[0].name} 的朝向和视线，不要无故翻转左右关系")

    if previous_shot is not None and str(getattr(getattr(previous_shot, 'detail', None), 'scene_id', '') or '') == str(detail.scene_id or ''):
        anchors.append("与上一镜头同场景时，尽量延续同一空间轴线和主体朝向")
    if next_shot is not None and str(getattr(getattr(next_shot, 'detail', None), 'scene_id', '') or '') == str(detail.scene_id or ''):
        anchors.append("与下一镜头同场景时，为后续镜头保留稳定的视觉落点与空间方向")

    return "；".join(anchors)


def _build_screen_direction_guidance(
    *,
    detail: ShotDetail,
    previous_shot: Shot | None,
    next_shot: Shot | None,
    dialogue_summary: str,
    character_names: list[str],
) -> str:
    """生成人物朝向、视线与左右轴线建议。"""
    guidance: list[str] = []
    angle = _enum_value(detail.angle)

    if angle == "OVER_SHOULDER":
        guidance.append("当前镜头为过肩视角，应保持前景肩部与被看对象的左右关系稳定")
    elif angle == "EYE_LEVEL":
        guidance.append("优先保持人物视线水平和对视方向稳定，避免无故翻转左右朝向")
    else:
        guidance.append("明确主体朝向和视线落点，避免人物突然改向或跳轴")

    if dialogue_summary.strip():
        guidance.append("存在对白时，优先保证说话者与受话者的视线关系连续")
    if len(character_names) >= 2:
        guidance.append(f"角色 {character_names[0]} 与 {character_names[1]} 的左右站位和对视方向应保持一致")
    elif character_names:
        guidance.append(f"角色 {character_names[0]} 的朝向与视线落点应在相邻镜头中保持延续")

    current_scene_id = str(detail.scene_id or "")
    previous_scene_id = str(getattr(getattr(previous_shot, "detail", None), "scene_id", "") or "")
    next_scene_id = str(getattr(getattr(next_shot, "detail", None), "scene_id", "") or "")
    if previous_shot is not None and current_scene_id and current_scene_id == previous_scene_id:
        guidance.append("与上一镜头同场景时，不要无故翻转人物面向和左右轴线")
    if next_shot is not None and current_scene_id and current_scene_id == next_scene_id:
        guidance.append("与下一镜头同场景时，当前镜头结尾应保留可延续的视线方向")

    return "；".join(guidance)


_SEQUENTIAL_REACTION_KEYWORDS = (
    "听到",
    "闻声",
    "忽然",
    "突然",
    "下意识",
    "立刻",
    "随即",
    "紧接着",
    "随后",
    "脱手",
    "掉在地上",
    "捂住耳朵",
    "捂住",
    "蹲下",
    "跪下",
    "跌坐",
    "转身",
    "回头",
)


def _has_sequential_reaction_chain(*values: str | None) -> bool:
    """判断文本是否包含明显的连续反应链，供首帧时间切片加权使用。"""
    text = " ".join(_compact_text(value) for value in values if _compact_text(value))
    if not text:
        return False
    keyword_hits = sum(1 for keyword in _SEQUENTIAL_REACTION_KEYWORDS if keyword in text)
    punctuation_hits = text.count("，") + text.count("。") + text.count("；") + text.count("、")
    return keyword_hits >= 2 or (keyword_hits >= 1 and punctuation_hits >= 2)


def _build_frame_specific_guidance(
    *,
    frame_type: str,
    previous_shot: Shot | None,
    next_shot: Shot | None,
    detail: ShotDetail,
    script_excerpt: str,
    action_beats: list[str],
) -> str:
    """按首帧/关键帧/尾帧生成专项提示，拉开三类帧职责差异。"""
    guidance: list[str] = []
    if frame_type == "first":
        guidance.append("首帧应优先建立空间、主体初始站位和第一眼视觉印象，不要直接跳到动作尾声")
        guidance.append("首帧只表现事件触发瞬间或最初反应的起始状态，不要直接写成后续完成动作、最终姿态或情绪爆发结果")
        guidance.append("若剧本存在连续反应链，优先写成动作刚开始、尚未完成或被打断的状态，例如手刚松脱、身体骤然僵住、人物尚未完全蹲下")
        if _has_sequential_reaction_chain(script_excerpt, detail.description):
            guidance.append("当前镜头存在明显连续反应链，首帧必须截取触发后最早的可见瞬间，禁止直接落到捂耳、蹲下、倒地或转身完成态")
        if previous_shot is not None:
            guidance.append("首帧要承接上一镜头结束状态，但仍应让观众迅速看清当前空间与主体起始状态")
        if _enum_value(detail.camera_shot) in {"LS", "ELS", "MLS"}:
            guidance.append("当前景别较大时，优先把环境、人物位置关系和进入方向交代清楚")
    elif frame_type == "last":
        guidance.append("尾帧应强调动作收束、情绪余韵或视线停留点，不要重新铺开新的动作起点")
        if next_shot is not None:
            guidance.append("尾帧应为下一镜头留下自然衔接的姿态、视线或情绪落点")
        guidance.append("尾帧中的主体姿态应更稳定，便于后续镜头承接")
    else:
        guidance.append("关键帧应锁定镜头内最有戏剧张力或信息密度最高的瞬间，不要平均描述整个过程")
        guidance.append("优先选择动作峰值、情绪爆点或构图最有代表性的瞬间")
        if _enum_value(detail.movement) in {"DOLLY_IN", "ZOOM_IN", "TRACK"}:
            guidance.append("若镜头存在推进或跟拍，关键帧应体现运动过程中最集中、最有压迫感的画面")
    beat_item = pick_action_beat_for_frame(frame_type, action_beats)
    if beat_item is not None:
        phase_label = {
            "trigger": "触发阶段",
            "peak": "峰值阶段",
            "aftermath": "收束阶段",
        }.get(beat_item.phase, "当前阶段")
        guidance.append(f"当前帧优先围绕动作拍点“{beat_item.text}”组织画面（{phase_label}），不要越级跳到其他阶段")
    return "；".join(guidance)


def _format_action_beat_phase_summary(action_beats: list[str]) -> str:
    """格式化动作拍点阶段摘要，供 agent 输入与调试预览复用。"""
    sequence = infer_action_beat_sequence(action_beats)
    phase_labels = {
        "trigger": "触发",
        "peak": "峰值",
        "aftermath": "收束",
    }
    return "；".join(
        f"{index + 1}. {phase_labels.get(item.phase, item.phase)} · {item.text}"
        for index, item in enumerate(sequence)
    )


def _same_scene(shot: Shot | None, current_scene_id: str) -> bool:
    """判断相邻镜头是否与当前镜头处于同一场景。"""
    return bool(
        shot is not None
        and current_scene_id
        and str(getattr(getattr(shot, "detail", None), "scene_id", "") or "") == current_scene_id
    )


def _score_director_guidance_item(
    *,
    category: str,
    text: str,
    frame_type: str,
    has_dialogue: bool,
    character_count: int,
    same_scene_with_previous: bool,
    same_scene_with_next: bool,
    movement: str,
) -> int:
    """为 guidance 句子打分，优先保留更能稳定镜头连续性的约束。"""
    score = 0
    if category == "frame":
        score += 10
        if frame_type == "first" and ("建立空间" in text or "起始状态" in text):
            score += 5
        if frame_type == "first" and ("触发瞬间" in text or "后续完成动作" in text or "尚未完成" in text):
            score += 6
        if frame_type == "first" and ("连续反应链" in text or "最早的可见瞬间" in text or "完成态" in text):
            score += 8
        if frame_type == "key" and ("动作峰值" in text or "戏剧张力" in text or "情绪爆点" in text):
            score += 5
        if frame_type == "last" and ("动作收束" in text or "情绪余韵" in text or "停留点" in text):
            score += 5
    elif category == "continuity":
        score += 8
        if "承接上一镜头" in text:
            score += 3
            if same_scene_with_previous:
                score += 4
        if "下一镜头" in text or "收束" in text:
            score += 3
            if same_scene_with_next:
                score += 4
        if "空间轴线" in text or "主体朝向稳定" in text or "视觉重心" in text:
            score += 3
    elif category == "composition":
        score += 7
        if frame_type == "first" and ("空间锚点" in text or "建立空间" in text):
            score += 5
        if frame_type == "key" and ("画面重心" in text or "推进" in text or "焦点" in text):
            score += 4
        if frame_type == "last" and ("视觉落点" in text or "空间方向" in text):
            score += 4
        if "锁定角色" in text or "重心位置" in text:
            score += 2
    elif category == "screen":
        score += 6
        if "不要无故翻转" in text or "跳轴" in text:
            score += 5
        if has_dialogue and ("视线关系连续" in text or "对视方向" in text):
            score += 5
        if character_count >= 2 and ("左右站位" in text or "对视方向" in text):
            score += 4
        if same_scene_with_previous or same_scene_with_next:
            if "同场景" in text or "视线方向" in text or "左右轴线" in text:
                score += 4
        if frame_type == "last" and "视线方向" in text:
            score += 2
    if movement in {"DOLLY_IN", "ZOOM_IN", "TRACK"} and category == "composition" and "推进" in text:
        score += 3
    return score


def _build_director_must_categories(
    *,
    frame_type: str,
    has_dialogue: bool,
    character_count: int,
    same_scene_with_previous: bool,
    same_scene_with_next: bool,
    movement: str,
) -> list[str]:
    """按镜头风险动态决定哪些 guidance 应提升为必须项。"""
    if frame_type == "first":
        must_categories = ["frame", "continuity", "composition"]
    elif frame_type == "key":
        must_categories = ["frame", "composition", "continuity"]
    else:
        must_categories = ["frame", "continuity", "screen"]

    if movement in {"DOLLY_IN", "ZOOM_IN", "TRACK"} and "composition" in must_categories:
        must_categories = ["composition" if item == "composition" else item for item in must_categories]
        must_categories.insert(0, must_categories.pop(must_categories.index("composition")))

    if has_dialogue or character_count >= 2 or same_scene_with_previous or same_scene_with_next:
        if "screen" not in must_categories:
            insert_at = 2 if frame_type == "key" else 1
            must_categories.insert(min(insert_at, len(must_categories)), "screen")
        elif frame_type == "last":
            must_categories.insert(1, must_categories.pop(must_categories.index("screen")))

    deduped: list[str] = []
    for category in must_categories:
        if category not in deduped:
            deduped.append(category)
    return deduped[:4]


def _build_director_command_summary(
    *,
    frame_type: str,
    frame_specific_guidance: str,
    continuity_guidance: str,
    composition_anchor: str,
    screen_direction_guidance: str,
    has_dialogue: bool,
    character_count: int,
    same_scene_with_previous: bool,
    same_scene_with_next: bool,
    movement: str,
) -> str:
    """将多类 guidance 压缩成高优先级导演指令摘要。"""
    seen: set[str] = set()

    def _split_bucket(category: str, block: str) -> list[str]:
        bucket: list[str] = []
        for piece in str(block or "").split("；"):
            text = piece.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            bucket.append(text)
        return sorted(
            bucket,
            key=lambda item: _score_director_guidance_item(
                category=category,
                text=item,
                frame_type=frame_type,
                has_dialogue=has_dialogue,
                character_count=character_count,
                same_scene_with_previous=same_scene_with_previous,
                same_scene_with_next=same_scene_with_next,
                movement=movement,
            ),
            reverse=True,
        )

    buckets = {
        "frame": _split_bucket("frame", frame_specific_guidance),
        "continuity": _split_bucket("continuity", continuity_guidance),
        "composition": _split_bucket("composition", composition_anchor),
        "screen": _split_bucket("screen", screen_direction_guidance),
    }
    must_categories = _build_director_must_categories(
        frame_type=frame_type,
        has_dialogue=has_dialogue,
        character_count=character_count,
        same_scene_with_previous=same_scene_with_previous,
        same_scene_with_next=same_scene_with_next,
        movement=movement,
    )

    must_items: list[str] = []
    prefer_items: list[str] = []
    consumed_must_items: set[str] = set()

    for category in must_categories:
        bucket = buckets.get(category) or []
        if bucket:
            must_items.append(bucket[0])
            consumed_must_items.add(bucket[0])

    frame_bucket = buckets.get("frame") or []
    if frame_type == "first" and len(frame_bucket) > 1:
        primary_frame_item = frame_bucket[0]
        if any(keyword in primary_frame_item for keyword in ("连续反应链", "触发瞬间", "尚未完成", "完成态")):
            secondary_frame_item = frame_bucket[1]
            if secondary_frame_item not in consumed_must_items:
                must_items.append(secondary_frame_item)
                consumed_must_items.add(secondary_frame_item)

    for category in ("frame", "continuity", "composition", "screen"):
        bucket = buckets.get(category) or []
        if category in must_categories and bucket:
            prefer_items.extend(item for item in bucket[1:] if item not in consumed_must_items)
            continue
        prefer_items.extend(item for item in bucket if item not in consumed_must_items)
        if category not in must_categories and bucket:
            head = bucket[0]
            if head not in consumed_must_items:
                prefer_items.insert(0, head)

    items = [*(f"必须：{item}" for item in must_items[:4]), *(f"优先：{item}" for item in prefer_items[:4])]
    if not items:
        return ""
    return "；".join(items[:8])


def _extract_context_names(context_text: str | None) -> list[str]:
    names: list[str] = []
    for raw_line in str(context_text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        body = line[2:]
        name = body.split("：", 1)[0].strip()
        if name:
            names.append(name)
    return names


def _cleanup_generated_prompt(prompt: str) -> str:
    text = str(prompt or "").strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned: list[str] = []
    after_generation_heading = False
    for line in lines:
        if line == "## 生成内容":
            after_generation_heading = True
            cleaned = []
            continue
        if line == "## 图片内容说明" or re.fullmatch(r"图\d+\s*[:：].*", line):
            continue
        cleaned.append(line)
    if after_generation_heading and cleaned:
        return "\n".join(cleaned).strip()
    return "\n".join(cleaned).strip()


def _validate_generated_prompt(prompt: str, input_dict: dict[str, object]) -> list[str]:
    issues: list[str] = []
    text = str(prompt or "").strip()
    if not text:
        return ["生成结果为空"]
    if "## 图片内容说明" in text or "## 生成内容" in text or re.search(r"(^|\n)\s*图\d+\s*[:：]", text):
        issues.append("结果混入了图片映射说明，应只保留基础提示词")
    primary_characters = _extract_context_names(str(input_dict.get("character_context") or ""))
    if primary_characters:
        lead_names = primary_characters[:2]
        if not any(name in text for name in lead_names):
            issues.append(f"结果缺少主角色名称：{'、'.join(lead_names)}")
    return issues


def _build_retry_guidance(issues: list[str]) -> str:
    if not issues:
        return ""
    return "请严格修正以下问题后重新生成：\n- " + "\n- ".join(issues)


async def build_run_args(
    db: AsyncSession,
    *,
    shot_id: str,
    frame_type: str,
) -> dict:
    normalized_frame_type = normalize_frame_type(frame_type)
    shot_stmt = (
        select(Shot)
        .options(
            selectinload(Shot.detail).selectinload(ShotDetail.dialog_lines),
            selectinload(Shot.detail).selectinload(ShotDetail.scene),
            selectinload(Shot.chapter).selectinload(Chapter.project),
            selectinload(Shot.character_links)
            .selectinload(ShotCharacterLink.character)
            .selectinload(Character.actor),
            selectinload(Shot.character_links)
            .selectinload(ShotCharacterLink.character)
            .selectinload(Character.costume),
            selectinload(Shot.scene_links).selectinload(ProjectSceneLink.scene),
            selectinload(Shot.prop_links).selectinload(ProjectPropLink.prop),
            selectinload(Shot.costume_links).selectinload(ProjectCostumeLink.costume),
        )
        .where(Shot.id == shot_id)
    )
    shot = (await db.execute(shot_stmt)).scalar_one_or_none()
    if shot is None:
        raise HTTPException(status_code=404, detail=entity_not_found("Shot"))
    if shot.detail is None:
        raise HTTPException(status_code=404, detail=entity_not_found("ShotDetail"))

    detail = shot.detail
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
    previous_title, previous_excerpt, previous_state = _summarize_neighbor_shot(previous_shot)
    next_title, next_excerpt, next_goal = _summarize_neighbor_shot(next_shot)
    dialog_summary = "\n".join(line.text for line in (detail.dialog_lines or []) if line.text)
    project = getattr(getattr(shot, "chapter", None), "project", None)
    visual_style = _enum_value(getattr(project, "visual_style", None))
    style = _enum_value(getattr(project, "style", None))
    unify_style = bool(getattr(project, "unify_style", True)) if project is not None else True

    characters = [
        link.character
        for link in sorted(list(getattr(shot, "character_links", []) or []), key=lambda item: (item.index, item.id))
        if getattr(link, "character", None) is not None
    ]
    scenes_by_id: dict[str, Scene] = {}
    detail_scene = getattr(detail, "scene", None)
    if detail_scene is not None:
        scenes_by_id[str(detail_scene.id)] = detail_scene
    for link in list(getattr(shot, "scene_links", []) or []):
        scene = getattr(link, "scene", None)
        if scene is not None:
            scenes_by_id[str(scene.id)] = scene
    props = [
        link.prop
        for link in list(getattr(shot, "prop_links", []) or [])
        if getattr(link, "prop", None) is not None
    ]
    costumes = [
        link.costume
        for link in list(getattr(shot, "costume_links", []) or [])
        if getattr(link, "costume", None) is not None
    ]
    scenes = list(scenes_by_id.values())

    continuity_guidance = _build_continuity_guidance(
        previous_shot=previous_shot,
        current_shot=shot,
        next_shot=next_shot,
    )
    action_beats = [str(item).strip() for item in list(getattr(detail, "action_beats", []) or []) if str(item).strip()]
    selected_action_beat = pick_action_beat_for_frame(normalized_frame_type, action_beats)
    action_beat_phases = _format_action_beat_phase_summary(action_beats)
    composition_anchor = _build_composition_anchor(
        detail=detail,
        previous_shot=previous_shot,
        next_shot=next_shot,
        characters=characters,
        scenes=scenes,
    )
    screen_direction_guidance = _build_screen_direction_guidance(
        detail=detail,
        previous_shot=previous_shot,
        next_shot=next_shot,
        dialogue_summary=dialog_summary,
        character_names=[character.name for character in characters],
    )
    frame_specific_guidance = _build_frame_specific_guidance(
        frame_type=normalized_frame_type,
        previous_shot=previous_shot,
        next_shot=next_shot,
        detail=detail,
        script_excerpt=shot.script_excerpt or "",
        action_beats=action_beats,
    )
    return {
        "shot_id": shot_id,
        "frame_type": normalized_frame_type,
        "input": {
            "script_excerpt": shot.script_excerpt or "",
            "title": shot.title or "",
            "visual_style": visual_style,
            "style": style,
            "unify_style": unify_style,
            "camera_shot": _enum_value(detail.camera_shot),
            "angle": _enum_value(detail.angle),
            "movement": _enum_value(detail.movement),
            "atmosphere": detail.atmosphere or "",
            "shot_description": detail.description or "",
            "mood_tags": detail.mood_tags or [],
            "vfx_type": _enum_value(detail.vfx_type),
            "vfx_note": detail.vfx_note or "",
            "duration": detail.duration,
            "scene_id": detail.scene_id,
            "dialog_summary": dialog_summary,
            "action_beats": action_beats,
            "action_beat_phases": action_beat_phases,
            "selected_action_beat_phase": getattr(selected_action_beat, "phase", ""),
            "selected_action_beat_text": getattr(selected_action_beat, "text", ""),
            "character_context": _build_character_context(characters),
            "scene_context": _build_named_asset_context(scenes),
            "prop_context": _build_named_asset_context(props),
            "costume_context": _build_named_asset_context(costumes),
            "subject_priority": _build_subject_priority(
                characters=characters,
                scenes=scenes,
                props=props,
                costumes=costumes,
            ),
            "previous_shot_title": previous_title,
            "previous_shot_script_excerpt": previous_excerpt,
            "previous_shot_end_state": previous_state,
            "next_shot_title": next_title,
            "next_shot_script_excerpt": next_excerpt,
            "next_shot_start_goal": next_goal,
            "continuity_guidance": continuity_guidance,
            "composition_anchor": composition_anchor,
            "screen_direction_guidance": screen_direction_guidance,
            "frame_specific_guidance": frame_specific_guidance,
            "director_command_summary": _build_director_command_summary(
                frame_type=normalized_frame_type,
                frame_specific_guidance=frame_specific_guidance,
                continuity_guidance=continuity_guidance,
                composition_anchor=composition_anchor,
                screen_direction_guidance=screen_direction_guidance,
                has_dialogue=bool(dialog_summary.strip()),
                character_count=len(characters),
                same_scene_with_previous=_same_scene(previous_shot, str(detail.scene_id or "")),
                same_scene_with_next=_same_scene(next_shot, str(detail.scene_id or "")),
                movement=_enum_value(detail.movement),
            ),
        },
    }


async def run_shot_frame_prompt_task(
    task_id: str,
    run_args: dict,
) -> None:
    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, 10)
            await session.commit()
            log_task_event("shot_frame_prompt", task_id, "running")
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("shot_frame_prompt", task_id, "cancelled", stage="before_execute")
                return

            frame_type = str(run_args.get("frame_type") or "")
            shot_id = str(run_args.get("shot_id") or "")
            input_dict = dict(run_args.get("input") or {})
            # B1：帧提示词模板可在后台编辑，配了就覆盖内置模板。
            frame_template_override = await resolve_frame_template_override(
                session, frame_type=frame_type
            )
            llm = await session.run_sync(lambda sync_db: build_default_text_llm_sync(sync_db, thinking=False))

            if frame_type == "first":
                agent = ShotFirstFramePromptAgent(llm, frame_template=frame_template_override)
            elif frame_type == "last":
                agent = ShotLastFramePromptAgent(llm, frame_template=frame_template_override)
            else:
                agent = ShotKeyFramePromptAgent(llm, frame_template=frame_template_override)
            input_dict.setdefault("retry_guidance", "")
            result = await agent.aextract(**input_dict)
            quality_issues = _validate_generated_prompt(result.prompt, input_dict)
            if quality_issues:
                retry_input = dict(input_dict)
                retry_input["retry_guidance"] = _build_retry_guidance(quality_issues)
                retry_result = await agent.aextract(**retry_input)
                retry_issues = _validate_generated_prompt(retry_result.prompt, retry_input)
                if not retry_issues:
                    input_dict = retry_input
                    result = retry_result
                    quality_issues = []
                else:
                    result.prompt = _cleanup_generated_prompt(retry_result.prompt) or _cleanup_generated_prompt(result.prompt) or result.prompt
                    input_dict = retry_input
                    quality_issues = retry_issues
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("shot_frame_prompt", task_id, "cancelled", stage="after_execute")
                return

            if not shot_id:
                raise RuntimeError("Missing shot_id in run args")
            shot_detail = await session.get(ShotDetail, shot_id)
            if shot_detail is None:
                raise RuntimeError("ShotDetail not found when persisting prompt")

            if frame_type == "first":
                shot_detail.first_frame_prompt = result.prompt
            elif frame_type == "last":
                shot_detail.last_frame_prompt = result.prompt
            else:
                shot_detail.key_frame_prompt = result.prompt

            result_payload = result.model_dump()
            result_payload["debug_context"] = dict(input_dict)
            result_payload["quality_checks"] = {
                "passed": not quality_issues,
                "issues": quality_issues,
            }
            await store.set_result(task_id, result_payload)
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("shot_frame_prompt", task_id, "cancelled", stage="after_persist")
                return
            await store.set_progress(task_id, 100)
            await store.set_status(task_id, TaskStatus.succeeded)
            await recompute_shot_status(session, shot_id=shot_id)
            await session.commit()
            log_task_event("shot_frame_prompt", task_id, "succeeded")
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with async_session_maker() as s2:
                store = SqlAlchemyTaskStore(s2)
                await store.set_error(task_id, str(exc))
                await store.set_status(task_id, TaskStatus.failed)
                shot_id = str(run_args.get("shot_id") or "")
                if shot_id:
                    await recompute_shot_status(s2, shot_id=shot_id)
                await s2.commit()
            log_task_failure("shot_frame_prompt", task_id, str(exc))
