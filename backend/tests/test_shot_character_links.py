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
    ShotCandidateStatus,
    ShotCandidateType,
    ShotCharacterLink,
    ShotExtractedCandidate,
)
from app.schemas.studio.cast import ShotCharacterLinkCreate
from app.services.studio.shot_character_links import list_by_shot, upsert


async def _build_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


async def _seed_base_graph(db: AsyncSession) -> None:
    project = Project(
        workspace_id="ws-test",
        id="p1",
        name="项目一",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )
    other_project = Project(
        workspace_id="ws-test",
        id="p2",
        name="项目二",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )
    chapter = Chapter(id="c1", project_id="p1", index=1, title="第一章")
    shot = Shot(id="s1", chapter_id="c1", index=1, title="镜头一")
    character_1 = Character(
        id="char1",
        project_id="p1",
        name="角色一",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )
    character_2 = Character(
        id="char2",
        project_id="p1",
        name="角色二",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )
    foreign_character = Character(
        id="char3",
        project_id="p2",
        name="跨项目角色",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )
    db.add_all([project, other_project, chapter, shot, character_1, character_2, foreign_character])
    await db.commit()


@pytest.mark.asyncio
async def test_upsert_rejects_character_from_other_project() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_base_graph(db)

        with pytest.raises(ValueError, match="same project"):
            await upsert(
                db,
                body=ShotCharacterLinkCreate(shot_id="s1", character_id="char3", index=0, note="bad"),
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_updates_existing_same_character_link() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_base_graph(db)

        created = await upsert(
            db,
            body=ShotCharacterLinkCreate(shot_id="s1", character_id="char1", index=0, note="first"),
        )
        updated = await upsert(
            db,
            body=ShotCharacterLinkCreate(shot_id="s1", character_id="char1", index=2, note="updated"),
        )

        rows = (await db.execute(select(ShotCharacterLink))).scalars().all()

        assert created.id == updated.id
        assert updated.index == 2
        assert updated.note == "updated"
        assert len(rows) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_replaces_existing_same_index_link() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_base_graph(db)

        first = await upsert(
            db,
            body=ShotCharacterLinkCreate(shot_id="s1", character_id="char1", index=1, note="first"),
        )
        second = await upsert(
            db,
            body=ShotCharacterLinkCreate(shot_id="s1", character_id="char2", index=1, note="second"),
        )

        listed = await list_by_shot(db, shot_id="s1")

        assert first.character_id == "char1"
        assert second.character_id == "char2"
        assert len(listed) == 1
        assert listed[0].character_id == "char2"
        assert listed[0].note == "second"
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_replaces_existing_same_index_link_marks_previous_candidate_back_to_pending() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_base_graph(db)
        candidate_1 = ShotExtractedCandidate(
            shot_id="s1",
            candidate_type=ShotCandidateType.character,
            candidate_name="角色一",
            candidate_status=ShotCandidateStatus.pending,
            source="extraction",
            payload={},
        )
        candidate_2 = ShotExtractedCandidate(
            shot_id="s1",
            candidate_type=ShotCandidateType.character,
            candidate_name="角色二",
            candidate_status=ShotCandidateStatus.pending,
            source="extraction",
            payload={},
        )
        db.add_all([candidate_1, candidate_2])
        await db.flush()

        await upsert(
            db,
            body=ShotCharacterLinkCreate(shot_id="s1", character_id="char1", index=1, note="first"),
        )
        await upsert(
            db,
            body=ShotCharacterLinkCreate(shot_id="s1", character_id="char2", index=1, note="second"),
        )

        refreshed_1 = await db.get(ShotExtractedCandidate, candidate_1.id)
        refreshed_2 = await db.get(ShotExtractedCandidate, candidate_2.id)
        assert refreshed_1 is not None
        assert refreshed_2 is not None
        assert refreshed_1.candidate_status == ShotCandidateStatus.pending
        assert refreshed_1.linked_entity_id is None
        assert refreshed_1.confirmed_at is None
        assert refreshed_2.candidate_status == ShotCandidateStatus.linked
        assert refreshed_2.linked_entity_id == "char2"
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_marks_matching_character_candidate_as_linked() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_base_graph(db)
        candidate = ShotExtractedCandidate(
            shot_id="s1",
            candidate_type=ShotCandidateType.character,
            candidate_name="角色一",
            candidate_status=ShotCandidateStatus.pending,
            source="extraction",
            payload={},
        )
        db.add(candidate)
        await db.flush()

        await upsert(
            db,
            body=ShotCharacterLinkCreate(shot_id="s1", character_id="char1", index=0, note="linked"),
        )

        refreshed = await db.get(ShotExtractedCandidate, candidate.id)
        assert refreshed is not None
        assert refreshed.candidate_status == ShotCandidateStatus.linked
        assert refreshed.linked_entity_id == "char1"
        assert refreshed.confirmed_at is not None
    await engine.dispose()
