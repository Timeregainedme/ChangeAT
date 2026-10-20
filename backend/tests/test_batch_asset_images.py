"""一键批量资产参考图生成服务的单测。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.task_manager.types import TaskStatus
from app.models.task import GenerationTask
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


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch) -> None:
    """批量服务只做 stage，测试中不真正把任务交给 Celery。"""
    monkeypatch.setattr(svc, "_enqueue", lambda task_id: None)


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
                workspace_id="ws-test",
                id="p1",
                name="项目一",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            ),
            Project(
                workspace_id="ws-test",
                id="p2",
                name="项目二",
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
            Character(
                id="char-empty",
                project_id="p1",
                name="无图角色",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            ),
            Character(
                id="char-other",
                project_id="p2",
                name="别项目的角色",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            ),
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
    """批量生成：返回 dict；缺图片槽位的角色会被自动补槽位后照常生成。"""
    db, engine = await _build_session()

    created_tasks: list[tuple[str, int]] = []

    async def _fake_create_single(db, *, asset_type, asset_id, image_id):
        created_tasks.append((asset_id, int(image_id)))
        return f"task-{asset_id}", f"prompt for {asset_id}"

    monkeypatch.setattr(svc, "_create_single_asset_image_task", _fake_create_single)

    async with db:
        await _seed_graph(db)
        result = await svc.create_batch_asset_image_tasks(db, asset_type="character", project_id="p1")

    # A-2：返回 dict，而非被错误包裹的单元素 list
    assert isinstance(result, dict)
    assert [item["asset_id"] for item in result["tasks"]] == ["char-abc", "char-empty"]
    assert result["tasks"][0]["task_id"] == "task-char-abc"
    assert result["tasks"][0]["prompt"] == "prompt for char-abc"
    assert result["skipped"] == []
    # char-abc 复用已有 front 槽位（id=1）；char-empty 由服务补了一个新槽位（B-8）
    assert created_tasks[0] == ("char-abc", 1)
    assert created_tasks[1][0] == "char-empty"
    assert created_tasks[1][1] > 0


@pytest.mark.asyncio
async def test_create_batch_asset_image_tasks_only_scans_project(monkeypatch) -> None:
    """A-3：缺省目标只扫本项目，不会带上其它项目的资产。"""
    db, engine = await _build_session()

    created: list[str] = []

    async def _fake_create_single(db, *, asset_type, asset_id, image_id):
        created.append(asset_id)
        return f"task-{asset_id}", "p"

    monkeypatch.setattr(svc, "_create_single_asset_image_task", _fake_create_single)

    async with db:
        await _seed_graph(db)
        result = await svc.create_batch_asset_image_tasks(db, asset_type="character", project_id="p1")

    assert created == ["char-abc", "char-empty"]
    assert "char-other" not in created
    assert all(item["asset_id"] != "char-other" for item in result["tasks"])


@pytest.mark.asyncio
async def test_create_batch_asset_image_tasks_rejects_foreign_asset_ids(monkeypatch) -> None:
    """A-3：显式传入其它项目的资产 ID 时被拒绝，不跨项目创建任务。"""
    db, engine = await _build_session()

    called: list[str] = []

    async def _fake_create_single(db, *, asset_type, asset_id, image_id):
        called.append(asset_id)
        return f"task-{asset_id}", "p"

    monkeypatch.setattr(svc, "_create_single_asset_image_task", _fake_create_single)

    async with db:
        await _seed_graph(db)
        result = await svc.create_batch_asset_image_tasks(
            db, asset_type="character", project_id="p1", asset_ids=["char-other"]
        )

    assert called == []
    assert result["tasks"] == []
    assert result["skipped"] == [{"asset_id": "char-other", "reason": "not in project"}]


@pytest.mark.asyncio
async def test_create_batch_asset_image_tasks_unknown_project() -> None:
    """项目不存在时报错。"""
    db, engine = await _build_session()
    async with db:
        await _seed_graph(db)
        with pytest.raises(ValueError):
            await svc.create_batch_asset_image_tasks(db, asset_type="character", project_id="nope")


@pytest.mark.asyncio
async def test_create_batch_asset_image_tasks_enforces_cap() -> None:
    """B-9：目标数量超过上限时直接报错，避免无界提交。"""
    db, engine = await _build_session()
    async with db:
        await _seed_graph(db)
        with pytest.raises(ValueError, match="too many assets"):
            await svc.create_batch_asset_image_tasks(
                db, asset_type="character", project_id="p1", max_assets=1
            )


@pytest.mark.asyncio
async def test_create_batch_asset_image_tasks_unsupported_type() -> None:
    """非法资产类型直接报错。"""
    db, engine = await _build_session()
    async with db:
        await _seed_graph(db)
        with pytest.raises(ValueError):
            await svc.create_batch_asset_image_tasks(db, asset_type="unknown", project_id="p1")


@pytest.mark.asyncio
async def test_create_batch_asset_image_tasks_midway_flush_failure_isolated(monkeypatch) -> None:
    """C-14：单个资产发生真实 flush 失败后，其余资产仍被正常 stage。

    构造真实的数据库错误（图片槽位主键冲突）而不是简单 raise：`create_entity` /
    图片槽位写入内部都有 `db.flush()`，flush 失败会把 session 打成 failed 态；
    没有 SAVEPOINT 隔离的话，后续资产会全部抛 PendingRollbackError 被误记 skipped。
    """
    db, engine = await _build_session()

    async def _fake_create_single(db, *, asset_type, asset_id, image_id):
        if asset_id == "char-abc":
            # 真实主键冲突：id=1 已被 _seed_graph 中的 CharacterImage 占用
            db.add(
                CharacterImage(
                    id=1,
                    character_id="char-empty",
                    view_angle=AssetViewAngle.front,
                    quality_level=AssetQualityLevel.low,
                    is_primary=True,
                )
            )
            await db.flush()
        return f"task-{asset_id}", f"prompt for {asset_id}"

    monkeypatch.setattr(svc, "_create_single_asset_image_task", _fake_create_single)

    async with db:
        await _seed_graph(db)
        result = await svc.create_batch_asset_image_tasks(db, asset_type="character", project_id="p1")

    assert [item["asset_id"] for item in result["tasks"]] == ["char-empty"]
    assert [item["asset_id"] for item in result["skipped"]] == ["char-abc"]
    assert result["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_create_batch_asset_image_tasks_marks_failed_when_enqueue_raises(monkeypatch) -> None:
    """D-12（批量路径）：入队失败的任务必须被标记 failed，不能永久停在 pending。

    任务行在入队之前就已 commit，因此入队抛错时若不落地失败状态，这些行会
    永远停留在 pending —— 既不会被 worker 捡起执行，也不会被任何清理逻辑回收。
    失败的任务应只出现在 `enqueue_failed`，不再计入 `tasks`（前端据此提示
    「已提交 N 个任务」，不能虚报）。
    """
    db, engine = await _build_session()

    async def _fake_create_single(db, *, asset_type, asset_id, image_id):
        # 真实 stage 会落一行 generation_tasks；这里补一行，好验证失败状态确实落库。
        task_id = f"task-{asset_id}"
        db.add(
            GenerationTask(
                id=task_id,
                workspace_id="ws-test",
                mode="async_polling",
                task_kind="image_generation",
            )
        )
        await db.flush()
        return task_id, f"prompt for {asset_id}"

    def _flaky_enqueue(task_id: str) -> None:
        if task_id == "task-char-abc":
            raise RuntimeError("broker down")

    monkeypatch.setattr(svc, "_create_single_asset_image_task", _fake_create_single)
    monkeypatch.setattr(svc, "_enqueue", _flaky_enqueue)

    async with db:
        await _seed_graph(db)
        result = await svc.create_batch_asset_image_tasks(
            db, asset_type="character", project_id="p1"
        )
        assert [item["asset_id"] for item in result["tasks"]] == ["char-empty"]
        assert result["enqueue_failed"] == [
            {"asset_id": "char-abc", "task_id": "task-char-abc", "reason": "broker down"}
        ]
        status = (
            await db.execute(
                select(GenerationTask.status).where(GenerationTask.id == "task-char-abc")
            )
        ).scalar_one()

    assert status == TaskStatus.failed