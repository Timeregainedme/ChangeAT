from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import (
    Chapter,
    FileItem,
    FileType,
    FileUsageKind,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Shot,
)
from app.schemas.studio.files import FileUpdate
from app.services.studio.files import get_file_detail, list_files_paginated, update_file_meta


async def _build_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


async def _seed_scope_graph(db: AsyncSession) -> None:
    project = Project(
        workspace_id="ws-test",
        id="p1",
        name="项目一",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )
    chapter = Chapter(id="c1", project_id="p1", index=1, title="第一章")
    shot = Shot(id="s1", chapter_id="c1", index=1, title="镜头一")
    db.add_all([project, chapter, shot])
    await db.commit()


@pytest.mark.asyncio
async def test_list_files_paginated_filters_by_keyword() -> None:
    db, engine = await _build_session()
    async with db:
        db.add_all(
            [
                FileItem(id="f1", type=FileType.image, name="角色主图", thumbnail="", tags=[], storage_key="files/a.png"),
                FileItem(id="f2", type=FileType.video, name="片段视频", thumbnail="", tags=[], storage_key="files/b.mp4"),
            ]
        )
        await db.commit()

        resp = await list_files_paginated(
            db,
            q="角色",
            order="name",
            is_desc=False,
            page=1,
            page_size=10,
        )

        assert resp.data is not None
        assert resp.data.pagination.total == 1
        assert [item.id for item in resp.data.items] == ["f1"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_file_detail_includes_usages() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_scope_graph(db)
        db.add(
            FileItem(
                id="f1",
                type=FileType.image,
                name="角色主图",
                thumbnail="thumb",
                tags=["hero"],
                storage_key="files/a.png",
            )
        )
        await db.commit()

        await update_file_meta(
            db,
            file_id="f1",
            body=FileUpdate(
                usage={
                    "project_id": "p1",
                    "chapter_id": "c1",
                    "shot_id": "s1",
                    "usage_kind": FileUsageKind.upload,
                    "source_ref": "manual",
                }
            ),
        )

        detail = await get_file_detail(db, file_id="f1")

        assert detail.id == "f1"
        assert len(detail.usages) == 1
        assert detail.usages[0].project_id == "p1"
        assert detail.usages[0].chapter_id == "c1"
        assert detail.usages[0].shot_id == "s1"
        assert detail.usages[0].usage_kind == FileUsageKind.upload
    await engine.dispose()


@pytest.mark.asyncio
async def test_update_file_meta_updates_fields_and_upserts_usage() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_scope_graph(db)
        db.add(
            FileItem(
                id="f1",
                type=FileType.image,
                name="旧名称",
                thumbnail="old",
                tags=["old"],
                storage_key="files/a.png",
            )
        )
        await db.commit()

        updated = await update_file_meta(
            db,
            file_id="f1",
            body=FileUpdate(
                name="新名称",
                thumbnail="new-thumb",
                tags=["hero", "poster"],
                usage={
                    "project_id": "p1",
                    "chapter_id": "c1",
                    "shot_id": "s1",
                    "usage_kind": FileUsageKind.asset_image,
                    "source_ref": "slot-1",
                },
            ),
        )
        updated_again = await update_file_meta(
            db,
            file_id="f1",
            body=FileUpdate(
                usage={
                    "project_id": "p1",
                    "chapter_id": "c1",
                    "shot_id": "s1",
                    "usage_kind": FileUsageKind.asset_image,
                    "source_ref": "slot-1",
                }
            ),
        )
        detail = await get_file_detail(db, file_id="f1")

        assert updated.name == "新名称"
        assert updated.thumbnail == "new-thumb"
        assert updated.tags == ["hero", "poster"]
        assert updated_again.id == "f1"
        assert len(detail.usages) == 1
        assert detail.usages[0].usage_kind == FileUsageKind.asset_image
        assert detail.usages[0].source_ref == "slot-1"
    await engine.dispose()
