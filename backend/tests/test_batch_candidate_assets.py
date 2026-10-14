"""一键从提取候选批量创建/关联资产的单测。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import (
    Chapter,
    Character,
    Project,
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
