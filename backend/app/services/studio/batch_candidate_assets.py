"""从提取候选批量创建资产并关联分镜的服务。

ToonFlow 式「一键提取资产」的核心落库步骤：
- 输入章节 ID（及可选的候选类型过滤）；
- 遍历该章节下所有 pending 提取候选（人物/场景/道具/服装）；
- 对每个候选：若项目内尚无同名实体则用候选 payload（description/voice_description 等）创建实体，
  并绑定到候选所在分镜；随后将候选标记为 linked；
- 同名实体已存在时直接关联已有实体，不重复创建；
- 每个候选包在自己的 SAVEPOINT 中执行：单个候选失败只回滚该候选，
  不会让 session 进入 failed 态而连累后续候选（`create_entity` 内部有 flush）。

`types=None` 表示不限定类型（处理全部）；`types=[]` 表示一个类型都不处理。
两者语义不同，避免「传空数组」被误解为「全部」。

返回逐候选的处理结果，供前端展示「新建 / 已关联 / 跳过」。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.common.errors import entity_not_found
from app.models.studio import (
    Chapter,
    Character,
    Costume,
    Prop,
    Scene,
    Shot,
    ShotCharacterLink,
    ShotExtractedCandidate,
)
from app.models.types import ShotCandidateStatus
from app.schemas.studio.cast import ShotCharacterLinkCreate
from app.services.studio.entity_crud import create_entity
from app.services.studio.entity_specs import LINK_MODEL_BY_ENTITY
from app.services.studio.shot_character_links import upsert as upsert_shot_character_link
from app.services.studio.shot_extracted_candidates import mark_linked_by_name
from app.utils.project_links import upsert_project_link

# 候选类型 → 实体类型名（与 entities 路由的 entity_type 对齐）。
_CANDIDATE_ENTITY_TYPE: dict[str, str] = {
    "character": "character",
    "scene": "scene",
    "prop": "prop",
    "costume": "costume",
}

# 非 character 实体类型 → 项目关联表（用于按项目查重）。
_LINK_MODEL_BY_ENTITY_TYPE: dict[str, tuple[Any, str]] = {
    entity_type: (model, asset_field)
    for entity_type, (model, asset_field) in LINK_MODEL_BY_ENTITY.items()
    if entity_type in {"scene", "prop", "costume"}
}

# 实体 ID 前缀（与前端创建角色时的 char-xxx 风格保持一致）。
_ENTITY_ID_PREFIX: dict[str, str] = {
    "character": "char",
    "scene": "scene",
    "prop": "prop",
    "costume": "costume",
}


def _new_entity_id(entity_type: str) -> str:
    """生成形如 `char-1a2b3c4d` 的实体 ID（与前端本地创建资产的 ID 风格保持一致）。"""
    return f"{_ENTITY_ID_PREFIX[entity_type]}-{uuid.uuid4().hex[:8]}"


async def _find_existing_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    project_id: str,
    name: str,
) -> str | None:
    """按 (项目, 名称) 找同名实体，返回实体 ID；不存在返回 None。

    character 直接按 project_id+name 查；scene/prop/costume 无 project_id 字段，
    通过项目关联表（project_scene_links 等）限定项目范围后按 name 查重。
    """
    if entity_type == "character":
        model: Any = Character
        stmt = (
            select(model.id)
            .where(model.project_id == project_id)  # type: ignore[attr-defined]
            .where(model.name == name)
            .limit(1)
        )
    else:
        link_model, asset_field = _LINK_MODEL_BY_ENTITY_TYPE[entity_type]
        model = {"scene": Scene, "prop": Prop, "costume": Costume}[entity_type]
        entity_id_col = getattr(link_model, asset_field)
        stmt = (
            select(entity_id_col)
            .join(model, model.id == entity_id_col)
            .where(link_model.project_id == project_id)
            .where(model.name == name)
            .limit(1)
        )
    row = (await db.execute(stmt)).scalars().first()
    return str(row) if row is not None else None


async def _link_existing_entity_to_shot(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    project_id: str,
    chapter_id: str,
    shot_id: str,
) -> None:
    """把「已存在」的实体关联到当前镜头。

    为什么需要这个函数：
        批量创建时若项目内已有同名实体，原逻辑走 existing 分支只做了
        `mark_linked_by_name`（把候选标记为 linked），**没有写入
        shot_character_links / project_prop_links / project_scene_links /
        project_costume_links**。于是只有「首次出现该实体的那个镜头」建立了关联，
        后续镜头虽然候选显示已关联，但 `linked-assets` 查不到，前端
        「关联图片（参考图）」显示不全。

    幂等：已存在关联时直接返回，不重复插入。
    """
    if entity_type == "character":
        exists = (
            await db.execute(
                select(ShotCharacterLink.id)
                .where(
                    ShotCharacterLink.shot_id == shot_id,
                    ShotCharacterLink.character_id == entity_id,
                )
                .limit(1)
            )
        ).scalars().first()
        if exists is not None:
            return
        max_index = (
            await db.execute(
                select(ShotCharacterLink.index)
                .where(ShotCharacterLink.shot_id == shot_id)
                .order_by(ShotCharacterLink.index.desc())
                .limit(1)
            )
        ).scalars().first()
        await upsert_shot_character_link(
            db,
            body=ShotCharacterLinkCreate(
                shot_id=shot_id,
                character_id=entity_id,
                index=(max_index if isinstance(max_index, int) else -1) + 1,
                note="",
            ),
        )
        return

    link_pair = LINK_MODEL_BY_ENTITY.get(entity_type)
    if link_pair is None:
        return
    link_model, asset_field = link_pair

    exists = (
        await db.execute(
            select(link_model.id)
            .where(
                getattr(link_model, asset_field) == entity_id,
                link_model.shot_id == shot_id,
            )
            .limit(1)
        )
    ).scalars().first()
    if exists is not None:
        return

    await upsert_project_link(
        db,
        model=link_model,
        asset_field=asset_field,  # type: ignore[arg-type]
        asset_id=entity_id,
        project_id=project_id,
        chapter_id=chapter_id,
        shot_id=shot_id,
    )


async def _create_entity_from_candidate(
    db: AsyncSession,
    *,
    entity_type: str,
    project_id: str,
    name: str,
    payload: dict[str, Any],
    chapter_id: str,
    shot_id: str,
) -> str:
    """用候选 payload 创建实体并绑定到分镜，返回实体 ID。"""
    body: dict[str, Any] = {
        "id": _new_entity_id(entity_type),
        "project_id": project_id,
        "name": name,
        "description": str(payload.get("description") or "").strip(),
        "chapter_id": chapter_id,
        "shot_id": shot_id,
    }
    if entity_type == "character":
        voice_description = str(payload.get("voice_description") or "").strip()
        if voice_description:
            body["voice_description"] = voice_description
    created = await create_entity(db, entity_type=entity_type, body=body)
    return str(created.get("id") or body["id"])


async def create_assets_from_extraction_candidates(
    db: AsyncSession,
    *,
    chapter_id: str,
    types: list[str] | None = None,
) -> dict[str, Any]:
    """按章节一键创建/关联提取候选资产。

    参数：
    - `chapter_id`：目标章节 ID，其下所有镜头的 pending 候选都会被处理；
    - `types`：候选类型过滤。`None` = 不限定（处理全部）；
      显式传空列表 `[]` = 一个类型都不处理（返回三个空列表），
      非法类型直接抛 ValueError。

    返回结构：
    {
      "created": [{candidate_id, type, name, entity_id}],
      "linked":  [{candidate_id, type, name, entity_id}],
      "skipped": [{candidate_id, type, name, reason}],
      # 角色 → 服装 的第二遍自动绑定结果（评审新增，用户需求 m08283）：
      "costume_bound":   [{candidate_id, character_id, character_name, costume_name, costume_id}],
      "costume_unbound": [{candidate_id, character_id, character_name, costume_name, reason}],
    }

    `costume_unbound[].reason` 取值：
    - `already_bound`：角色已经有服装，不覆盖用户的选择；
    - `costume_not_found`：项目内没有同名服装；
    - `character_not_found`：角色实体意外不存在；
    - 其它为底层异常文本。
    """
    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        raise ValueError(entity_not_found("Chapter"))
    project_id = chapter.project_id

    # D-11：区分 None（不限定＝全部）与 []（一个都不处理）。
    allow_types: set[str] | None = None
    if types is not None:
        allow_types = {str(x).strip().lower() for x in types}
        invalid = allow_types - set(_CANDIDATE_ENTITY_TYPE)
        if invalid:
            raise ValueError(f"unsupported candidate types: {sorted(invalid)}")
    if allow_types is not None and not allow_types:
        # 显式空数组：没有任何类型需要处理，直接返回空结果（而不是误当作「全部」）。
        return {"created": [], "linked": [], "skipped": []}

    # 章节下所有镜头 → 所有 pending 候选（按 shot、候选类型、名称排序保证确定性）
    shot_ids_stmt = select(Shot.id).where(Shot.chapter_id == chapter_id)
    shot_ids = [str(x) for x in (await db.execute(shot_ids_stmt)).scalars().all()]
    if not shot_ids:
        return {"created": [], "linked": [], "skipped": []}

    candidates_stmt = (
        select(ShotExtractedCandidate)
        .where(ShotExtractedCandidate.shot_id.in_(shot_ids))
        .where(ShotExtractedCandidate.candidate_status == ShotCandidateStatus.pending)
        .order_by(
            ShotExtractedCandidate.shot_id.asc(),
            ShotExtractedCandidate.candidate_type.asc(),
            ShotExtractedCandidate.candidate_name.asc(),
        )
    )
    candidates = list((await db.execute(candidates_stmt)).scalars().all())

    created: list[dict[str, Any]] = []
    linked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    # 角色 → 服装 的绑定意图，第一遍只登记，第二遍再落库（原因见循环后的注释）。
    # 元组：(角色实体 ID, 角色名, 候选里带的 costume_name, 候选 ID)
    character_costume_intents: list[tuple[str, str, str, int]] = []

    for cand in candidates:
        candidate_type = str(getattr(cand.candidate_type, "value", cand.candidate_type))
        if allow_types is not None and candidate_type not in allow_types:
            continue
        entity_type = _CANDIDATE_ENTITY_TYPE[candidate_type]
        name = str(cand.candidate_name or "").strip()
        if not name:
            skipped.append({"candidate_id": cand.id, "type": candidate_type, "name": name, "reason": "empty name"})
            continue

        payload = dict(cand.payload or {})
        try:
            # C-14：每个候选一个 SAVEPOINT。create_entity 内部会 db.flush()，
            # flush 失败会让 session 进入 failed 态；不用 SAVEPOINT 隔离的话，
            # 后续候选会全部抛 PendingRollbackError 被误记为 skipped。
            async with db.begin_nested():
                existing_id = await _find_existing_entity(
                    db, entity_type=entity_type, project_id=project_id, name=name
                )
                if existing_id is None:
                    entity_id = await _create_entity_from_candidate(
                        db,
                        entity_type=entity_type,
                        project_id=project_id,
                        name=name,
                        payload=payload,
                        chapter_id=chapter_id,
                        shot_id=cand.shot_id,
                    )
                else:
                    entity_id = existing_id
                    # 复用已有实体时也必须建立「镜头 ↔ 资产」关联，
                    # 否则后续镜头看不到该资产（前端参考图显示不全）。
                    await _link_existing_entity_to_shot(
                        db,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        project_id=project_id,
                        chapter_id=chapter_id,
                        shot_id=cand.shot_id,
                    )

                await mark_linked_by_name(
                    db,
                    shot_id=cand.shot_id,
                    candidate_type=candidate_type,
                    candidate_name=name,
                    linked_entity_id=entity_id,
                )

                # 角色候选带着 costume_name 时登记绑定意图（第二遍统一落库）。
                if entity_type == "character":
                    costume_name_intent = str(payload.get("costume_name") or "").strip()
                    if costume_name_intent:
                        character_costume_intents.append((entity_id, name, costume_name_intent, cand.id))
        except Exception as exc:  # noqa: BLE001 - 单候选失败不阻断批量
            skipped.append({"candidate_id": cand.id, "type": candidate_type, "name": name, "reason": str(exc)})
            continue

        entry = {"candidate_id": cand.id, "type": candidate_type, "name": name, "entity_id": entity_id}
        # C-13：登记必须放在 SAVEPOINT 成功之后。
        # 若在 try 内提前 append，一旦随后的 mark_linked_by_name 抛错，
        # 同一候选会既出现在 created/linked 又出现在 skipped，前端出现「新建 1 / 跳过 1」双报。
        if existing_id is None:
            created.append(entry)
        else:
            linked.append(entry)

    # ---------------- 第二遍：角色 → 服装 按名称自动绑定 ----------------
    # 为什么必须单独一遍：候选按 `candidate_type` 升序处理，而 'character' < 'costume'，
    # 所以第一遍处理角色时，同名服装实体很可能还没被创建，当场按名字查必然查不到。
    # 等所有实体都建好后再统一解析，才能覆盖「服装候选排在角色候选之后」的情况。
    #
    # 绑定规则（保守，不做破坏性覆盖）：
    #   - 只在角色当前 `costume_id` 为空时写入；
    #   - 用户已手工选过服装的角色一律跳过（reason=already_bound）；
    #   - 项目内找不到同名服装时不写入（reason=costume_not_found），只回报不报错。
    # 绑定失败逐个隔离在 SAVEPOINT 内，不影响已经建好的资产与分镜关联。
    costume_bound: list[dict[str, Any]] = []
    costume_unbound: list[dict[str, Any]] = []
    for character_id, character_name, costume_name, candidate_id in character_costume_intents:
        entry_base: dict[str, Any] = {
            "candidate_id": candidate_id,
            "character_id": character_id,
            "character_name": character_name,
            "costume_name": costume_name,
        }
        try:
            async with db.begin_nested():
                character = await db.get(Character, character_id)
                if character is None:
                    costume_unbound.append({**entry_base, "reason": "character_not_found"})
                    continue
                if (getattr(character, "costume_id", None) or "").strip():
                    costume_unbound.append({**entry_base, "reason": "already_bound"})
                    continue
                costume_id = await _find_existing_entity(
                    db, entity_type="costume", project_id=project_id, name=costume_name
                )
                if costume_id is None:
                    costume_unbound.append({**entry_base, "reason": "costume_not_found"})
                    continue
                character.costume_id = costume_id
                await db.flush()
                costume_bound.append({**entry_base, "costume_id": costume_id})
        except Exception as exc:  # noqa: BLE001 - 单个绑定失败不阻断批量
            costume_unbound.append({**entry_base, "reason": str(exc)})

    return {
        "created": created,
        "linked": linked,
        "skipped": skipped,
        "costume_bound": costume_bound,
        "costume_unbound": costume_unbound,
    }
