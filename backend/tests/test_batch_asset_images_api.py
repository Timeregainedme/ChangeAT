"""一键批量资产参考图生成：路由级（TestClient）用例。

为什么存在（对应评审 C-18）：
- 既有批量资产测试全部直调 service，`response_model` 与真实返回形状不符（A-2 类
  「必然 500」）在 service 层测不出来，只能在路由层暴露；
- 需要覆盖路由级边界：缺参、未知项目、非法类型、asset_ids 超 200、项目内超上限、
  跨项目资产 ID、以及单个资产失败后其余资产仍被处理。

实现方式：用真实内存 SQLite 会话覆盖 `get_db`，让真实 service 在 HTTP 请求内跑通；
仅把「生成任务落库」这一深调用（`_create_single_asset_image_task`）替换为替身，
避免依赖真实图片模型/供应商配置。项目校验、上限、跨项目过滤、SAVEPOINT 隔离、
响应组织全部走真实代码。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.studio import (
    AssetQualityLevel,
    AssetViewAngle,
    Character,
    CharacterImage,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
)
from app.services.studio import batch_asset_images as svc


ENDPOINT = "/api/v1/studio/image-tasks/assets/batch-image-tasks"

# 已创建的会话环境；用例结束后统一 dispose，避免内存 SQLite 连接被 GC 回收时刷警告。
_ENVS: list["_DbEnv"] = []


@pytest.fixture(autouse=True)
def _dispose_envs() -> AsyncGenerator[None, None]:
    """用例结束后关闭会话与引擎，保持测试输出干净。"""
    yield
    for env in _ENVS:
        asyncio.run(env.close())
    _ENVS.clear()


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch) -> None:
    """路由级用例同样不允许把任务真正交给 Celery。"""
    monkeypatch.setattr(svc, "_enqueue", lambda task_id: None)


@pytest.fixture(autouse=True)
def _stub_stage(monkeypatch) -> None:
    """替换 stage 深调用：本文件只验证路由/编排/响应，不依赖图片模型与供应商配置。"""

    async def _fake_create_single(db, *, asset_type, asset_id, image_id):
        return f"task-{asset_id}", f"prompt for {asset_id}"

    monkeypatch.setattr(svc, "_create_single_asset_image_task", _fake_create_single)


class _DbEnv:
    """一个进程内独立的内存 SQLite 会话环境（每个用例一份新库）。"""

    def __init__(self, session: AsyncSession, engine: Any) -> None:
        self.session = session
        self.engine = engine

    @property
    def override(self) -> Callable[[], AsyncGenerator[AsyncSession, None]]:
        """覆盖 `get_db`：直接复用已建好的会话（批量服务自身会 commit）。"""

        async def _get_db() -> AsyncGenerator[AsyncSession, None]:
            yield self.session

        return _get_db

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """在独立事件循环里对该会话执行异步断言。"""
        return asyncio.run(coro)

    async def close(self) -> None:
        """关闭会话与引擎（用例结束后的清理）。"""
        await self.session.close()
        await self.engine.dispose()


def _make_env(seed: Callable[[AsyncSession], Coroutine[Any, Any, None]]) -> _DbEnv:
    """建库 + 建表 + 灌种子数据。"""

    async def _setup() -> _DbEnv:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = session_local()
        await seed(session)
        await session.commit()
        return _DbEnv(session, engine)

    env = asyncio.run(_setup())
    _ENVS.append(env)
    return env


def _character(character_id: str, project_id: str = "p1") -> Character:
    """构造一个满足非空约束的角色行。"""
    return Character(
        id=character_id,
        project_id=project_id,
        name=character_id,
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )


async def _seed_graph(db: AsyncSession) -> None:
    """种子数据：2 个项目；p1 下 2 个有图槽位的角色 + 1 个无槽位的角色；p2 下 1 个角色。"""
    db.add_all(
        [
            Project(
                id="p1",
                name="项目一",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            ),
            Project(
                id="p2",
                name="项目二",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            ),
            _character("char-a"),
            _character("char-b"),
            _character("char-empty"),
            _character("char-other", project_id="p2"),
            CharacterImage(
                id=1,
                character_id="char-a",
                view_angle=AssetViewAngle.front,
                quality_level=AssetQualityLevel.low,
                is_primary=True,
            ),
            CharacterImage(
                id=2,
                character_id="char-b",
                view_angle=AssetViewAngle.front,
                quality_level=AssetQualityLevel.low,
                is_primary=True,
            ),
        ]
    )


async def _seed_over_cap(db: AsyncSession) -> None:
    """种子数据：p1 下超过单次批量上限（200）的角色，用于触发上限保护。"""
    db.add(
        Project(
            id="p1",
            name="项目一",
            description="",
            style=ProjectStyle.real_people_city,
            visual_style=ProjectVisualStyle.live_action,
        )
    )
    db.add_all([_character(f"char-{index:03d}") for index in range(svc.MAX_BATCH_ASSETS + 1)])


def _use_env(env: _DbEnv) -> None:
    app.dependency_overrides[get_db] = env.override


def _clear_env() -> None:
    app.dependency_overrides.clear()


def test_batch_image_tasks_route_returns_real_envelope_shape(client: TestClient) -> None:
    """C-18 / D-12：路由级断言真实状态码与响应形状。

    - HTTP 201（批量创建资源）且响应体 `code` 同为 201（此前是 201 状态 + 200 业务码的自相矛盾）；
    - `data` 是 `{"tasks": [...], "skipped": [...], "enqueue_failed": [...]}` dict，
      而非被错误包裹的单元素 list。
    """
    env = _make_env(_seed_graph)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"project_id": "p1", "asset_type": "character"})
    finally:
        _clear_env()

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 201
    assert body["message"] == "success"
    assert body["meta"] is None
    data = body["data"]
    assert isinstance(data, dict)
    assert set(data) == {"tasks", "skipped", "enqueue_failed"}
    assert data["enqueue_failed"] == []
    # char-empty 无槽位 → 由服务按需补槽位后照常生成（B-8 行为在路由层同样成立）
    assert [item["asset_id"] for item in data["tasks"]] == ["char-a", "char-b", "char-empty"]
    assert data["tasks"][0] == {
        "asset_id": "char-a",
        "task_id": "task-char-a",
        "prompt": "prompt for char-a",
    }
    assert data["skipped"] == []

    async def _slot_created_for_empty() -> bool:
        stmt = select(CharacterImage.id).where(CharacterImage.character_id == "char-empty")
        return (await env.session.execute(stmt)).scalars().first() is not None

    assert env.run(_slot_created_for_empty())


def test_batch_image_tasks_route_requires_project_id_and_asset_type(client: TestClient) -> None:
    """边界（缺参）：project_id / asset_type 缺失 → 422，不进入 service。"""
    env = _make_env(_seed_graph)
    _use_env(env)
    try:
        missing_project = client.post(ENDPOINT, json={"asset_type": "character"})
        missing_type = client.post(ENDPOINT, json={"project_id": "p1"})
    finally:
        _clear_env()

    assert missing_project.status_code == 422
    assert missing_project.json()["code"] == 422
    assert missing_type.status_code == 422
    assert missing_type.json()["code"] == 422


def test_batch_image_tasks_route_unknown_project_returns_404(client: TestClient) -> None:
    """边界：未知项目 → 404（`Project not found` 走 value_error_handler 的 404 分支）。"""
    env = _make_env(_seed_graph)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"project_id": "nope", "asset_type": "character"})
    finally:
        _clear_env()

    assert response.status_code == 404
    assert response.json() == {
        "code": 404,
        "message": "Project not found",
        "data": None,
        "meta": None,
    }


def test_batch_image_tasks_route_unsupported_type_returns_400(client: TestClient) -> None:
    """边界（非法类型）：未知 asset_type → 400 错误壳，而不是 500。"""
    env = _make_env(_seed_graph)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"project_id": "p1", "asset_type": "video"})
    finally:
        _clear_env()

    assert response.status_code == 400
    assert response.json() == {
        "code": 400,
        "message": "unsupported asset_type: video",
        "data": None,
        "meta": None,
    }


def test_batch_image_tasks_route_rejects_too_many_asset_ids(client: TestClient) -> None:
    """边界（超限）：asset_ids 超过 schema `max_length=200` → 422。"""
    env = _make_env(_seed_graph)
    _use_env(env)
    try:
        response = client.post(
            ENDPOINT,
            json={
                "project_id": "p1",
                "asset_type": "character",
                "asset_ids": [f"char-{index}" for index in range(svc.MAX_BATCH_ASSETS + 1)],
            },
        )
    finally:
        _clear_env()

    assert response.status_code == 422
    assert response.json()["code"] == 422


def test_batch_image_tasks_route_over_cap_returns_400(client: TestClient) -> None:
    """边界（超上限）：项目内资产数超过单次批量上限 → 400，避免无界提交生成任务。"""
    env = _make_env(_seed_over_cap)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"project_id": "p1", "asset_type": "character"})
    finally:
        _clear_env()

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 400
    assert body["data"] is None
    assert "too many assets" in body["message"]


def test_batch_image_tasks_route_foreign_asset_ids_reported_as_skipped(
    client: TestClient,
) -> None:
    """边界：显式传入其它项目的资产 ID → 真实响应里进 skipped，不跨项目建任务。"""
    env = _make_env(_seed_graph)
    _use_env(env)
    try:
        response = client.post(
            ENDPOINT,
            json={"project_id": "p1", "asset_type": "character", "asset_ids": ["char-a", "char-other"]},
        )
    finally:
        _clear_env()

    assert response.status_code == 201
    data = response.json()["data"]
    assert [item["asset_id"] for item in data["tasks"]] == ["char-a"]
    assert data["skipped"] == [{"asset_id": "char-other", "reason": "not in project"}]


def test_batch_image_tasks_route_midway_failure_keeps_processing_rest(
    client: TestClient, monkeypatch
) -> None:
    """C-14：单个资产 stage 失败后，其余资产仍必须被 stage（SAVEPOINT 隔离）。"""
    original = svc._create_single_asset_image_task

    async def _failing_create_single(db, *, asset_type, asset_id, image_id):
        if asset_id == "char-b":
            # 真实主键冲突：图片槽位 id=1 已被占用，flush 失败会把 session 打成 failed 态
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
        return await original(db, asset_type=asset_type, asset_id=asset_id, image_id=image_id)

    monkeypatch.setattr(svc, "_create_single_asset_image_task", _failing_create_single)

    env = _make_env(_seed_graph)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"project_id": "p1", "asset_type": "character"})
    finally:
        _clear_env()

    assert response.status_code == 201
    data = response.json()["data"]
    assert [item["asset_id"] for item in data["tasks"]] == ["char-a", "char-empty"]
    assert [item["asset_id"] for item in data["skipped"]] == ["char-b"]
    assert data["skipped"][0]["reason"]
