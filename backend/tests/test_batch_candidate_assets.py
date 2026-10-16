"""一键从提取候选批量创建/关联资产的单测。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import (
    Chapter,
    Character,
    Costume,
    Project,
    ProjectCostumeLink,
    ProjectStyle,
    ProjectVisualStyle,
    Shot,
    ShotExtractedCandidate,
)
from app.models.types import ShotCandidateStatus, ShotCandidateType
from app.services.studio.batch_candidate_assets import create_assets_from_extraction_candidates


async def _build_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


async def _seed_graph(db: AsyncSession) -> None:
    db.add_all(
        [
            Project(
                id="p1",
                name="项目一",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            ),
            Chapter(id="c1", project_id="p1", index=1, title="第一章"),
            Shot(id="s1", chapter_id="c1", index=1, title="镜头一"),
            Shot(id="s2", chapter_id="c1", index=2, title="镜头二"),
            ShotExtractedCandidate(
                shot_id="s1",
                candidate_type=ShotCandidateType.character,
                candidate_name="小雨",
                candidate_status=ShotCandidateStatus.pending,
                payload={"description": "25岁互联网运营", "voice_description": "青年女声，清亮温柔，语速偏快"},
            ),
            ShotExtractedCandidate(
                shot_id="s1",
                candidate_type=ShotCandidateType.scene,
                candidate_name="十平米出租屋",
                candidate_status=ShotCandidateStatus.pending,
                payload={"description": "狭窄出租屋，顶灯冷白"},
            ),
            ShotExtractedCandidate(
                shot_id="s2",
                candidate_type=ShotCandidateType.character,
                candidate_name="小雨",
                candidate_status=ShotCandidateStatus.pending,
                payload={"description": "25岁互联网运营"},
            ),
            ShotExtractedCandidate(
                shot_id="s2",
                candidate_type=ShotCandidateType.prop,
                candidate_name="欠条",
                candidate_status=ShotCandidateStatus.pending,
                payload={"description": "写满数字的欠条"},
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_batch_create_assets_creates_and_links_candidates() -> None:
    """一键提取：创建角色（含音色描述）、场景、道具，并关联到分镜、候选标记 linked。"""
    db, engine = await _build_session()
    async with db:
        await _seed_graph(db)

        result = await create_assets_from_extraction_candidates(db, chapter_id="c1")

        # 2 条同名角色候选 → 只创建 1 个角色；场景/道具各 1
        assert len(result["created"]) == 3, result
        assert len(result["linked"]) == 1, result
        assert len(result["skipped"]) == 0, result

        chars = list((await db.execute(select(Character))).scalars().all())
        assert len(chars) == 1
        assert chars[0].name == "小雨"
        assert chars[0].voice_description == "青年女声，清亮温柔，语速偏快"
        assert chars[0].project_id == "p1"

        # 候选项全部变为 linked，且关联到同一角色
        rows = list((await db.execute(select(ShotExtractedCandidate))).scalars().all())
        assert all(r.candidate_status == ShotCandidateStatus.linked for r in rows)
        character_candidates = [r for r in rows if r.candidate_type == ShotCandidateType.character]
        assert len({r.linked_entity_id for r in character_candidates}) == 1


@pytest.mark.asyncio
async def test_batch_create_assets_links_existing_entity() -> None:
    """项目内已存在同名角色时：直接关联已有实体，不重复创建。"""
    db, engine = await _build_session()
    async with db:
        await _seed_graph(db)
        db.add(
            Character(
                id="char-existing",
                project_id="p1",
                name="小雨",
                description="已存在",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            )
        )
        await db.commit()

        result = await create_assets_from_extraction_candidates(db, chapter_id="c1", types=["character"])

        assert len(result["created"]) == 0
        assert len(result["linked"]) == 2, result
        chars = list((await db.execute(select(Character))).scalars().all())
        assert len(chars) == 1  # 未重复创建


@pytest.mark.asyncio
async def test_batch_create_assets_type_filter() -> None:
    """按类型过滤：只处理指定类型的候选。"""
    db, engine = await _build_session()
    async with db:
        await _seed_graph(db)

        result = await create_assets_from_extraction_candidates(db, chapter_id="c1", types=["scene"])

        assert len(result["created"]) == 1
        assert result["created"][0]["type"] == "scene"


# ---------------------------------------------------------------------------
# 角色 → 服装 的自动绑定（第二遍）
#
# 背景（用户需求 m08283）：ElementExtractorAgent 的 characters 结构本来就产出
# `costume_name?`，草稿 schema 的注释也写明「导入时映射到 costume_id」，但候选 payload
# 此前把它丢掉，导致一键创建资产建出的角色从不绑服装。
#
# 关键在于「候选按 candidate_type 升序处理，'character' < 'costume'」：第一遍跑到角色时
# 同名服装实体还没建出来，所以绑定必须放在所有实体建完之后的第二遍做。
# ---------------------------------------------------------------------------


async def _seed_character_with_costume_name(db: AsyncSession, *, costume_name: str | None) -> None:
    """种子：一个带 costume_name 的角色候选；costume_name 为 None 时不带该键。"""
    payload: dict[str, object] = {"description": "25岁互联网运营"}
    if costume_name is not None:
        payload["costume_name"] = costume_name
    db.add_all(
        [
            Project(
                id="p1",
                name="项目一",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            ),
            Chapter(id="c1", project_id="p1", index=1, title="第一章"),
            Shot(id="s1", chapter_id="c1", index=1, title="镜头一"),
            ShotExtractedCandidate(
                shot_id="s1",
                candidate_type=ShotCandidateType.character,
                candidate_name="小雨",
                candidate_status=ShotCandidateStatus.pending,
                payload=payload,
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_batch_create_assets_auto_binds_character_costume_by_name() -> None:
    """角色候选带 costume_name 时：建完服装后自动写入 characters.costume_id。

    这条用例同时守护「第二遍」这个设计：服装候选按类型排序排在角色候选**之后**，
    如果绑定写在第一遍里，此刻同名服装还不存在，必然查不到。
    """
    db, engine = await _build_session()
    async with db:
        await _seed_character_with_costume_name(db, costume_name="破旧校服")
        db.add(
            ShotExtractedCandidate(
                shot_id="s1",
                candidate_type=ShotCandidateType.costume,
                candidate_name="破旧校服",
                candidate_status=ShotCandidateStatus.pending,
                payload={"description": "洗得发白的蓝白校服"},
            )
        )
        await db.commit()

        result = await create_assets_from_extraction_candidates(db, chapter_id="c1")

        assert len(result["costume_bound"]) == 1, result
        assert result["costume_unbound"] == [], result
        bound = result["costume_bound"][0]
        assert bound["costume_name"] == "破旧校服"
        assert bound["character_name"] == "小雨"

        chars = list((await db.execute(select(Character))).scalars().all())
        assert len(chars) == 1
        # 角色确实落到了那条被本次批量创建出来的服装上。
        assert chars[0].costume_id == bound["costume_id"]
        costume = (await db.execute(select(Costume).where(Costume.id == chars[0].costume_id))).scalars().one()
        assert costume.name == "破旧校服"


@pytest.mark.asyncio
async def test_batch_create_assets_keeps_user_chosen_costume() -> None:
    """角色已经手工选过服装：自动绑定不覆盖，只回报 already_bound。"""
    db, engine = await _build_session()
    async with db:
        await _seed_character_with_costume_name(db, costume_name="破旧校服")
        db.add_all(
            [
                Costume(
                    id="costume-manual",
                    name="手工选的礼服",
                    description="",
                    style=ProjectStyle.real_people_city,
                    visual_style=ProjectVisualStyle.live_action,
                ),
                ShotExtractedCandidate(
                    shot_id="s1",
                    candidate_type=ShotCandidateType.costume,
                    candidate_name="破旧校服",
                    candidate_status=ShotCandidateStatus.pending,
                    payload={"description": "洗得发白的蓝白校服"},
                ),
                Character(
                    id="char-existing",
                    project_id="p1",
                    name="小雨",
                    description="已存在",
                    style=ProjectStyle.real_people_city,
                    visual_style=ProjectVisualStyle.live_action,
                    costume_id="costume-manual",
                ),
            ]
        )
        await db.commit()

        result = await create_assets_from_extraction_candidates(db, chapter_id="c1")

        assert result["costume_bound"] == [], result
        assert [u["reason"] for u in result["costume_unbound"]] == ["already_bound"], result
        char = (await db.execute(select(Character).where(Character.id == "char-existing"))).scalars().one()
        assert char.costume_id == "costume-manual"


@pytest.mark.asyncio
async def test_batch_create_assets_reports_missing_costume_without_failing() -> None:
    """项目内没有同名服装：不写入、不报错，只回报 costume_not_found。"""
    db, engine = await _build_session()
    async with db:
        await _seed_character_with_costume_name(db, costume_name="不存在的服装")

        result = await create_assets_from_extraction_candidates(db, chapter_id="c1")

        assert len(result["created"]) == 1
        assert result["costume_bound"] == [], result
        assert [u["reason"] for u in result["costume_unbound"]] == ["costume_not_found"], result
        chars = list((await db.execute(select(Character))).scalars().all())
        assert chars[0].costume_id is None


@pytest.mark.asyncio
async def test_batch_create_assets_without_costume_name_records_no_intent() -> None:
    """候选没带 costume_name（历史数据）：不产生任何绑定意图，两个新键都为空。"""
    db, engine = await _build_session()
    async with db:
        await _seed_character_with_costume_name(db, costume_name=None)

        result = await create_assets_from_extraction_candidates(db, chapter_id="c1")

        assert result["costume_bound"] == []
        assert result["costume_unbound"] == []
        chars = list((await db.execute(select(Character))).scalars().all())
        assert chars[0].costume_id is None
        # 项目关联表未被牵动（没有服装被创建/关联）。
        links = list((await db.execute(select(ProjectCostumeLink))).scalars().all())
        assert links == []
