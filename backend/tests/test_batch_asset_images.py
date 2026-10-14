"""一键批量资产参考图生成服务的单测。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import (
    AssetQualityLevel,
    AssetViewAngle,
    Chapter,
    Character,
    CharacterImage,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Scene,
    SceneImage,
    Shot,
)
from app.services.studio import batch_asset_images as svc


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
            Character(
                id="char-abc",
                project_id="p1",
                name="小雨",
                description="25岁互联网运营",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            ),
            CharacterImage(
                id=1,
                character_id="char-abc",
                view_angle=AssetViewAngle.front,
                quality_level=AssetQualityLevel.low,
                is_primary=True,
            ),
            CharacterImage(
                id=2,
                character_id="char-abc",
                view_angle=AssetViewAngle.left,
                quality_level=AssetQualityLevel.low,
                is_primary=False,
            ),
            Character(id="char-empty", project_id="p1", name="无图角色", description="", style=ProjectStyle.real_people_city, visual_style=ProjectVisualStyle.live_action),
            Scene(id="scene-1", name="出租屋", description="窄小", style=ProjectStyle.real_people_city),
            SceneImage(id=10, scene_id="scene-1", view_angle=AssetViewAngle.front, quality_level=AssetQualityLevel.low),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_pick_primary_image_id_prefers_front() -> None:
    """front 视角槽位优先于其他视角。"""
    db, engine = await _build_session()
    async with db:
        await _seed_graph(db)
        image_id = await svc.pick_primary_image_id(db, asset_type="character", asset_id="char-abc")
        assert image_id == 1


@pytest.mark.asyncio
async def test_pick_primary_image_id_none_when_no_slots() -> None:
    """无图片槽位的资产返回 None。"""
    db, engine = await _build_session()
    async with db:
        await _seed_graph(db)
        assert await svc.pick_primary_image_id(db, asset_type="character", asset_id="char-empty") is None


@pytest.mark.asyncio
async def test_create_batch_asset_image_tasks_mocks_pipeline(monkeypatch) -> None:
    """批量生成：每个有槽位资产生成一个任务；无槽位资产进 skipped。"""
    db, engine = await _build_session()

    created_tasks: list[tuple[str, str]] = []

    async def _fake_create_single(db, *, asset_type, asset_id, image_id):
        created_tasks.append((asset_id, str(image_id)))
        return f"task-{asset_id}", f"prompt for {asset_id}"

    monkeypatch.setattr(svc, "_create_single_asset_image_task", _fake_create_single)

    async with db:
        await _seed_graph(db)
        result = await svc.create_batch_asset_image_tasks(
            db, asset_type="character", asset_ids=["char-abc", "char-empty"]
        )

    # 服务返回结构为单元素列表包裹 dict（沿用现有批量路由的 response 约定）
    assert len(result) == 1
    body = result[0]
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["asset_id"] == "char-abc"
    assert body["tasks"][0]["task_id"] == "task-char-abc"
    assert body["skipped"][0]["asset_id"] == "char-empty"
    assert created_tasks == [("char-abc", "1")]


@pytest.mark.asyncio
async def test_create_batch_asset_image_tasks_unsupported_type() -> None:
    """非法资产类型直接报错。"""
    db, engine = await _build_session()
    async with db:
        with pytest.raises(ValueError):
            await svc.create_batch_asset_image_tasks(db, asset_type="unknown")
