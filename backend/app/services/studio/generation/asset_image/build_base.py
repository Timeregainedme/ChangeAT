from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from pydantic import Field

from app.chains.prompts.style_pack import negative_image_prompt, style_pack_line
from app.models.studio import (
    Actor,
    ActorImage,
    AssetViewAngle,
    Character,
    Costume,
    CostumeImage,
    PromptCategory,
    Prop,
    PropImage,
    Scene,
    SceneImage,
)
from app.services.common import entity_not_found
from app.services.studio.character_recurrence import character_chapter_count, is_recurring
from app.services.studio.generation.shared.types import GenerationBaseDraft
from app.services.studio.image_task_references import (
    pick_front_ref_file_id,
    pick_ordered_ref_file_ids,
)
from app.services.studio.image_task_validation import (
    validate_actor_image,
    validate_asset_image_and_relation_type,
    validate_character_image,
)
from app.services.studio.image_tasks import (
    asset_prompt_category,
    build_prompt_with_template,
    is_front_view,
    map_view_angle_for_prompt,
)


class AssetImageBaseDraft(GenerationBaseDraft):
    """资产图片生成的基础真值。"""

    kind: str = "asset_image"
    entity_type: str
    entity_id: str
    image_id: int
    relation_type: str
    relation_entity_id: str
    prompt: str
    default_images: list[str]
    # 参考图缺失的**显式**说明。
    # 为什么必须回传：角色图会引用「所绑演员的图片 + 所绑服装的图片」，但当角色没绑演员/服装、
    # 或所绑资产的图片槽位还是空的，`default_images` 就是空列表，而生成**照样会成功** ——
    # 用户在结果里只会看到一张「不像某个人」的图，无法归因到「其实没用到任何参考图」。
    # 这些文案把缺失提前到**发起前**可见（参考图缺失不得静默）。
    reference_warnings: list[str] = Field(default_factory=list)


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


async def _build_asset_prompt(
    db,
    *,
    relation_type: str,
    name: str,
    description: str,
    tags: list[str] | None,
    visual_style: Any,
    style: Any,
    image_row: Any,
) -> str:
    category = asset_prompt_category(
        relation_type=relation_type,
        is_front_view=is_front_view(image_row.view_angle),
    )
    return await build_prompt_with_template(
        db,
        category=category,
        variables={
            "name": name,
            "description": description,
            "tags": ", ".join(tags or []),
            "visual_style": _enum_value(visual_style),
            "style": _enum_value(style),
            "view_angle": map_view_angle_for_prompt(image_row.view_angle),
            "quality_level": image_row.quality_level,
            "format": image_row.format,
            # C2：项目级风格包一处配置、全局注入
            "style_pack": style_pack_line(visual_style=visual_style, style=style),
            "negative_prompt": negative_image_prompt(visual_style=visual_style, style=style),
        },
        fallback_prompt=description,
        not_found_msg=f"{relation_type}.description is empty",
    )


async def _resolve_front_ref(
    db,
    *,
    image_model,
    parent_field_name: str,
    parent_id: str,
    preferred_quality_level: str | None,
) -> list[str]:
    file_id = await pick_front_ref_file_id(
        db,
        image_model=image_model,
        parent_field_name=parent_field_name,
        parent_id=parent_id,
        preferred_quality_level=preferred_quality_level,
    )
    return [file_id] if file_id else []


async def build_actor_image_base_draft(
    db,
    *,
    actor_id: str,
    image_id: int | None,
) -> AssetImageBaseDraft:
    actor = await db.get(Actor, actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("Actor"))
    image_row = await validate_actor_image(db, actor_id=actor_id, image_id=image_id)
    prompt = await _build_asset_prompt(
        db,
        relation_type="actor_image",
        name=actor.name,
        description=actor.description,
        tags=actor.tags,
        visual_style=actor.visual_style,
        style=actor.style,
        image_row=image_row,
    )
    refs: list[str] = []
    warnings: list[str] = []
    if not is_front_view(image_row.view_angle):
        refs = await _resolve_front_ref(
            db,
            image_model=ActorImage,
            parent_field_name="actor_id",
            parent_id=actor_id,
            preferred_quality_level=image_row.quality_level,
        )
        if not refs:
            warnings.append(
                "缺少正面参考图：该演员还没有 front 视角的图片，本次是非正面视角生成，"
                "没有可用的参考图，视角一致性无法保证。建议先生成正面图再生成其它视角。"
            )
    return AssetImageBaseDraft(
        entity_type="actor",
        entity_id=actor_id,
        image_id=image_row.id,
        relation_type="actor_image",
        relation_entity_id=str(image_row.id),
        prompt=prompt,
        default_images=refs,
        reference_warnings=warnings,
    )


async def build_asset_image_base_draft(
    db,
    *,
    asset_type: str,
    asset_id: str,
    image_id: int | None,
) -> AssetImageBaseDraft:
    relation_entity_id, relation_type = await validate_asset_image_and_relation_type(
        db,
        asset_type=asset_type,
        asset_id=asset_id,
        image_id=image_id,
    )
    asset_type_norm = asset_type.strip().lower()
    refs: list[str] = []
    warnings: list[str] = []
    if asset_type_norm == "prop":
        asset = await db.get(Prop, asset_id)
        image_row = await db.get(PropImage, relation_entity_id)
        image_model = PropImage
        parent_field_name = "prop_id"
    elif asset_type_norm == "scene":
        asset = await db.get(Scene, asset_id)
        image_row = await db.get(SceneImage, relation_entity_id)
        image_model = SceneImage
        parent_field_name = "scene_id"
    else:
        asset = await db.get(Costume, asset_id)
        image_row = await db.get(CostumeImage, relation_entity_id)
        image_model = CostumeImage
        parent_field_name = "costume_id"
    if asset is None or image_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("AssetImage"))
    prompt = await _build_asset_prompt(
        db,
        relation_type=relation_type,
        name=asset.name,
        description=asset.description,
        tags=asset.tags,
        visual_style=asset.visual_style,
        style=asset.style,
        image_row=image_row,
    )
    if not is_front_view(image_row.view_angle):
        refs = await _resolve_front_ref(
            db,
            image_model=image_model,
            parent_field_name=parent_field_name,
            parent_id=asset_id,
            preferred_quality_level=image_row.quality_level,
        )
        if not refs:
            warnings.append(
                "缺少正面参考图：该资产还没有 front 视角的图片，本次是非正面视角生成，"
                "没有可用的参考图，视角一致性无法保证。建议先生成正面图再生成其它视角。"
            )
    return AssetImageBaseDraft(
        entity_type=asset_type.strip().lower(),
        entity_id=asset_id,
        image_id=relation_entity_id,
        relation_type=relation_type,
        relation_entity_id=str(relation_entity_id),
        prompt=prompt,
        default_images=refs,
        reference_warnings=warnings,
    )


async def build_character_image_base_draft(
    db,
    *,
    character_id: str,
    image_id: int | None,
) -> AssetImageBaseDraft:
    character = await db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("Character"))
    image_row = await validate_character_image(db, character_id=character_id, image_id=image_id)
    prompt = await build_prompt_with_template(
        db,
        category=PromptCategory.character_image_front,
        variables={
            "name": character.name,
            "description": character.description,
            "visual_style": _enum_value(character.visual_style),
            "style": _enum_value(character.style),
            "view_angle": map_view_angle_for_prompt(image_row.view_angle),
            "quality_level": image_row.quality_level,
            "format": image_row.format,
            # C2：项目级风格包一处配置、全局注入
            "style_pack": style_pack_line(
                visual_style=character.visual_style, style=character.style
            ),
            "negative_prompt": negative_image_prompt(
                visual_style=character.visual_style, style=character.style
            ),
        },
        fallback_prompt=character.description,
        not_found_msg="Character.description is empty",
    )
    refs: list[str] = []
    warnings: list[str] = []
    default_view_angles: tuple[AssetViewAngle, ...] = (
        AssetViewAngle.front,
        AssetViewAngle.left,
        AssetViewAngle.right,
        AssetViewAngle.back,
    )
    # 角色图 = 演员参考图 + 服装参考图。两条来源**各自**独立判定缺失：
    # 只报「总数为 0」会让用户以为「两个都没配」，而实际更常见的是只缺其中一个。
    if character.actor_id:
        actor_refs = await pick_ordered_ref_file_ids(
            db,
            image_model=ActorImage,
            parent_field_name="actor_id",
            parent_id=character.actor_id,
            view_angles=default_view_angles,
        )
        refs.extend(actor_refs)
        if not actor_refs:
            warnings.append(
                "所绑演员还没有生成任何图片，本次生成拿不到演员参考图，"
                "角色长相无法与该演员保持一致。建议先到「演员」页生成演员图。"
            )
    else:
        # 未绑定演员只对「主角级」角色报警：按用户口径（m09145），只在一集内出现的角色
        # 本来就不需要绑演员，对它们提示等同于噪音，会淹没真正要处理的问题。
        actor_chapter_count = await character_chapter_count(db, character_id=character_id)
        if is_recurring(actor_chapter_count):
            warnings.append(
                "角色未绑定演员，本次生成没有演员参考图，角色长相完全由文字描述决定。"
                f"该角色已出现在 {actor_chapter_count} 个章节，属于跨集反复出现的主角级角色，"
                "建议在角色编辑里绑定演员，以保证各集长相一致（系统不做名字匹配，名字相同也要绑）。"
            )
    if character.costume_id:
        costume_refs = await pick_ordered_ref_file_ids(
            db,
            image_model=CostumeImage,
            parent_field_name="costume_id",
            parent_id=character.costume_id,
            view_angles=default_view_angles,
        )
        refs.extend(costume_refs)
        if not costume_refs:
            warnings.append(
                "所绑服装还没有生成任何图片，本次生成拿不到服装参考图，服装细节无法与设定保持一致。"
                "建议先到「服装」页生成服装图。"
            )
    else:
        warnings.append("角色未绑定服装，本次生成没有服装参考图，服装完全由文字描述决定。")
    if not refs:
        # 只有两个来源都为空才走到这里：这是最危险的情形，必须单独、显式地讲明后果。
        warnings.append(
            "本次生成将在零参考图的情况下进行：角色外观完全由文字描述决定，"
            "可能与演员/服装设定不一致。建议先补齐演员图与服装图再生成。"
        )
    return AssetImageBaseDraft(
        entity_type="character",
        entity_id=character_id,
        image_id=image_row.id,
        relation_type="character_image",
        relation_entity_id=str(image_row.id),
        prompt=prompt,
        default_images=refs,
        reference_warnings=warnings,
    )
