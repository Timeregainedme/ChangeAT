"""Studio 实体主资源 CRUD。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import apply_keyword_filter, apply_order, paginate
from app.models.studio import (
    Actor,
    Chapter,
    Character,
    Costume,
    Project,
    ProjectActorLink,
    ProjectCostumeLink,
    ProjectPropLink,
    ProjectSceneLink,
    Prop,
    Scene,
    Shot,
    ShotCharacterLink,
)
from app.schemas.studio.cast import ShotCharacterLinkCreate
from app.services.common import entity_already_exists, entity_not_found
from app.services.studio.entity_specs import DEFAULT_VIEW_ANGLES, LINK_MODEL_BY_ENTITY, entity_spec, normalize_entity_type
from app.services.studio.entity_thumbnails import resolve_thumbnails
from app.services.studio.shot_character_links import upsert as upsert_shot_character_link
from app.utils.project_links import upsert_project_link

ENTITY_ORDER_FIELDS = {"name", "style", "visual_style", "created_at", "updated_at"}

# 「全局资产模型 → 项目关联表 → 关联外键字段」。
# Character 不在其中：它是项目内资产，自身直接持有 project_id。
_GLOBAL_ASSET_LINK_JOIN: dict[type, tuple[type, str]] = {
    Actor: (ProjectActorLink, "actor_id"),
    Scene: (ProjectSceneLink, "scene_id"),
    Prop: (ProjectPropLink, "prop_id"),
    Costume: (ProjectCostumeLink, "costume_id"),
}


def _link_join_for_entity(model: type) -> tuple[type, str]:
    """返回全局资产对应的项目关联表与外键字段。

    未知模型直接抛错而不是静默跳过过滤 —— 漏过滤会变成跨租户数据泄露，
    宁可让测试/上线前就炸出来。
    """
    try:
        return _GLOBAL_ASSET_LINK_JOIN[model]
    except KeyError as exc:  # pragma: no cover - 新增资产类型时的显式失败
        raise RuntimeError(f"缺少工作区归属映射：{model.__name__}") from exc


def _asset_read_payload(obj: Any, thumbnail: str) -> dict[str, Any]:
    return {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "tags": obj.tags or [],
        "prompt_template_id": obj.prompt_template_id,
        "view_count": obj.view_count,
        "style": obj.style,
        "visual_style": obj.visual_style,
        "thumbnail": thumbnail,
    }


async def list_entities_paginated(
    db: AsyncSession,
    *,
    entity_type: str,
    q: str | None,
    style: str | None,
    visual_style: str | None,
    order: str | None,
    is_desc: bool,
    page: int,
    page_size: int,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """分页查询资产实体。

    `workspace_id` 非空时按实体自身的 project_id 过滤。
    资产表直接持有 project_id（见 `studio_assets.py`），无需多跳，
    因此这里用 join projects 而不是子查询，便于 MySQL 用上 workspace 索引。
    """
    entity_type_norm = normalize_entity_type(entity_type)
    spec = entity_spec(entity_type_norm)
    stmt = select(spec.model)
    if workspace_id is not None:
        # 归属链分两类（详见 `app/api/scoping.py::get_entity_in_workspace`）：
        # Character 是项目内资产，自身持有 project_id；
        # Scene/Prop/Costume/Actor 是全局资产，需经各自的 project_*_links 关联表。
        if spec.model is Character:
            stmt = stmt.join(Project, Project.id == Character.project_id).where(
                Project.workspace_id == workspace_id
            )
        else:
            link_model, link_field = _link_join_for_entity(spec.model)
            stmt = (
                stmt.join(link_model, getattr(link_model, link_field) == spec.model.id)
                .join(Project, Project.id == link_model.project_id)
                .where(Project.workspace_id == workspace_id)
            )
    stmt = apply_keyword_filter(stmt, q=q, fields=[spec.model.name, spec.model.description])
    if style:
        stmt = stmt.where(getattr(spec.model, "style") == style)
    if visual_style:
        stmt = stmt.where(getattr(spec.model, "visual_style") == visual_style)
    stmt = apply_order(
        stmt,
        model=spec.model,
        order=order,
        is_desc=is_desc,
        allow_fields=ENTITY_ORDER_FIELDS,
        default="created_at",
    )
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)

    thumbnails = await resolve_thumbnails(
        db,
        image_model=spec.image_model,
        parent_field_name=spec.id_field,
        parent_ids=[item.id for item in items],
    )
    payload: list[dict[str, Any]] = []
    for item in items:
        thumbnail = thumbnails.get(item.id, "")
        if entity_type_norm in {"actor", "character"}:
            read_model = spec.read_model
            payload.append(read_model.model_validate(item).model_copy(update={"thumbnail": thumbnail}).model_dump())
        else:
            payload.append(_asset_read_payload(item, thumbnail))
    return payload, total


async def create_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    entity_type_norm = normalize_entity_type(entity_type)
    spec = entity_spec(entity_type_norm)
    parsed = spec.create_model.model_validate(body)
    data = parsed.model_dump()

    link_project_id: str | None = None
    link_chapter_id: str | None = None
    link_shot_id: str | None = None
    if entity_type_norm in LINK_MODEL_BY_ENTITY:
        link_project_id = data.pop("project_id", None)
        link_chapter_id = data.pop("chapter_id", None)
        link_shot_id = data.pop("shot_id", None)
    elif entity_type_norm == "character":
        link_project_id = data.get("project_id")
        link_chapter_id = data.pop("chapter_id", None)
        link_shot_id = data.pop("shot_id", None)

    exists = await db.get(spec.model, data["id"])
    if exists is not None:
        raise HTTPException(status_code=400, detail=entity_already_exists(spec.model.__name__))

    if entity_type_norm == "character":
        if await db.get(Project, data["project_id"]) is None:
            raise HTTPException(status_code=400, detail=entity_not_found("Project"))
        if data.get("actor_id") and await db.get(Actor, data["actor_id"]) is None:
            raise HTTPException(status_code=400, detail=entity_not_found("Actor"))
        if data.get("costume_id") and await db.get(Costume, data["costume_id"]) is None:
            raise HTTPException(status_code=400, detail=entity_not_found("Costume"))
        chapter: Chapter | None = None
        shot: Shot | None = None
        if link_chapter_id is not None:
            chapter = await db.get(Chapter, link_chapter_id)
            if chapter is None:
                raise HTTPException(status_code=400, detail=entity_not_found("Chapter"))
            if chapter.project_id != data["project_id"]:
                raise HTTPException(status_code=400, detail="Chapter does not belong to the same project")
        if link_shot_id is not None:
            shot = await db.get(Shot, link_shot_id)
            if shot is None:
                raise HTTPException(status_code=400, detail=entity_not_found("Shot"))
            shot_chapter = await db.get(Chapter, shot.chapter_id)
            if shot_chapter is None:
                raise HTTPException(status_code=400, detail=f"{entity_not_found('Chapter')} for shot")
            if shot_chapter.project_id != data["project_id"]:
                raise HTTPException(status_code=400, detail="Shot does not belong to the same project")
            if chapter is not None and shot.chapter_id != chapter.id:
                raise HTTPException(status_code=400, detail="Shot does not belong to the specified chapter")

    obj = spec.model(**data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)

    if entity_type_norm in {"actor", "scene", "prop", "costume"}:
        count = int(getattr(obj, "view_count", 1) or 1)
        angles = list(DEFAULT_VIEW_ANGLES[: min(max(count, 0), len(DEFAULT_VIEW_ANGLES))])
        for angle in angles:
            db.add(spec.image_model(**{spec.id_field: obj.id, "view_angle": angle}))
        if angles:
            await db.flush()

    if link_project_id is not None and entity_type_norm in LINK_MODEL_BY_ENTITY:
        link_model, asset_field = LINK_MODEL_BY_ENTITY[entity_type_norm]
        await upsert_project_link(
            db,
            model=link_model,
            asset_field=asset_field,  # type: ignore[arg-type]
            asset_id=obj.id,
            project_id=link_project_id,
            chapter_id=link_chapter_id,
            shot_id=link_shot_id,
        )

    if entity_type_norm == "character" and link_shot_id is not None:
        existing_indexes_stmt = (
            select(ShotCharacterLink.index)
            .where(ShotCharacterLink.shot_id == link_shot_id)
            .order_by(ShotCharacterLink.index.desc())
            .limit(1)
        )
        max_index = (await db.execute(existing_indexes_stmt)).scalars().first()
        await upsert_shot_character_link(
            db,
            body=ShotCharacterLinkCreate(
                shot_id=link_shot_id,
                character_id=obj.id,
                index=(max_index if isinstance(max_index, int) else -1) + 1,
                note="",
            ),
        )

    if entity_type_norm in {"actor", "character"}:
        read_model = spec.read_model
        payload = read_model.model_validate(obj).model_dump()
        payload["thumbnail"] = ""
        return payload
    return _asset_read_payload(obj, "")


async def get_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
) -> dict[str, Any]:
    entity_type_norm = normalize_entity_type(entity_type)
    spec = entity_spec(entity_type_norm)
    obj = await db.get(spec.model, entity_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=entity_not_found(spec.model.__name__))

    thumbnails = await resolve_thumbnails(
        db,
        image_model=spec.image_model,
        parent_field_name=spec.id_field,
        parent_ids=[entity_id],
    )
    thumbnail = thumbnails.get(entity_id, "")
    if entity_type_norm in {"actor", "character"}:
        read_model = spec.read_model
        return read_model.model_validate(obj).model_copy(update={"thumbnail": thumbnail}).model_dump()
    return _asset_read_payload(obj, thumbnail)


async def update_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    entity_type_norm = normalize_entity_type(entity_type)
    spec = entity_spec(entity_type_norm)
    obj = await db.get(spec.model, entity_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=entity_not_found(spec.model.__name__))

    update_data = spec.update_model.model_validate(body).model_dump(exclude_unset=True)
    if entity_type_norm == "character":
        if "project_id" in update_data and await db.get(Project, update_data["project_id"]) is None:
            raise HTTPException(status_code=400, detail=entity_not_found("Project"))
        if "actor_id" in update_data and update_data["actor_id"] is not None and await db.get(Actor, update_data["actor_id"]) is None:
            raise HTTPException(status_code=400, detail=entity_not_found("Actor"))
        if "costume_id" in update_data and update_data["costume_id"] is not None and await db.get(Costume, update_data["costume_id"]) is None:
            raise HTTPException(status_code=400, detail=entity_not_found("Costume"))

    for key, value in update_data.items():
        setattr(obj, key, value)
    await db.flush()
    await db.refresh(obj)

    if entity_type_norm in {"actor", "character"}:
        read_model = spec.read_model
        payload = read_model.model_validate(obj).model_dump()
        payload["thumbnail"] = ""
        return payload
    return _asset_read_payload(obj, "")


async def delete_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
) -> None:
    spec = entity_spec(entity_type)
    obj = await db.get(spec.model, entity_id)
    if obj is None:
        return
    await db.delete(obj)
    await db.flush()
