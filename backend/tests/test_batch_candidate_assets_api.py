"""一键从提取候选创建资产：路由级（TestClient）用例。

为什么存在（对应评审 C-13 / C-14 / C-18、D-11）：
- 既有批量资产测试全部直调 service，测不出「路由 `response_model` 与实际返回形状不符
  → 必然 500」这类只在路由层暴露的问题（A-2 生产事故的根源）；
- 需要一个用例证明「单个候选失败不会污染整个批量会话」（C-14），以及
  「同一候选不会既算新建又算跳过」（C-13）；
- 需要覆盖空章节 / 非法 types / 重复提交 / 超出数量上限等边界（C-18）。

实现方式：用**真实的内存 SQLite 会话**覆盖 `get_db`，让真实 service 在 HTTP 请求内完整跑通，
因此断言的响应形状就是生产环境经 FastAPI `response_model` 序列化后的真实形状，
而不是手写替身的形状。
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
    Chapter,
    Character,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Prop,
    Shot,
    ShotExtractedCandidate,
)
from app.models.types import ShotCandidateStatus, ShotCandidateType
from app.services.studio import batch_candidate_assets as svc


ENDPOINT = "/api/v1/studio/shots/extracted-candidates/batch-create-assets"

# 已创建的会话环境；用例结束后统一 dispose，避免内存 SQLite 连接被 GC 回收时刷警告。
_ENVS: list["_DbEnv"] = []


@pytest.fixture(autouse=True)
def _dispose_envs() -> AsyncGenerator[None, None]:
    """用例结束后关闭会话与引擎，保持测试输出干净。"""
    yield
    for env in _ENVS:
        asyncio.run(env.close())
    _ENVS.clear()


class _DbEnv:
    """一个进程内独立的内存 SQLite 会话环境（每个用例一份新库）。"""

    def __init__(self, session: AsyncSession, engine: Any) -> None:
        self.session = session
        self.engine = engine

    @property
    def override(self) -> Callable[[], AsyncGenerator[AsyncSession, None]]:
        """返回覆盖 `get_db` 的依赖：直接复用已建好的会话。

        为什么直接 yield 而不 commit：本文件的用例把「一次请求」当作一个事务单元，
        重复提交用例需要在同一会话内观察上一次请求的未提交结果。
        """

        async def _get_db() -> AsyncGenerator[AsyncSession, None]:
            yield self.session

        return _get_db

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """在独立事件循环里对该会话执行一段异步操作（用于断言落库结果）。"""
        return asyncio.run(coro)

    async def close(self) -> None:
        await self.session.close()
        await self.engine.dispose()


def _make_env(seed: Callable[[AsyncSession], Coroutine[Any, Any, None]]) -> _DbEnv:
    """建库 + 建表 + 灌种子数据，返回可直接给 TestClient 用的会话环境。"""

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


def _project(project_id: str = "p1", name: str = "项目一") -> Project:
    """构造一个满足非空约束的项目行。"""
    return Project(
        workspace_id="ws-test",
        id=project_id,
        name=name,
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )


def _candidate(
    shot_id: str,
    candidate_type: ShotCandidateType,
    name: str,
    *,
    payload: dict[str, Any] | None = None,
) -> ShotExtractedCandidate:
    """构造一个 pending 状态的提取候选。"""
    return ShotExtractedCandidate(
        shot_id=shot_id,
        candidate_type=candidate_type,
        candidate_name=name,
        candidate_status=ShotCandidateStatus.pending,
        payload=payload or {"description": f"{name} 的描述"},
    )


async def _seed_full_graph(db: AsyncSession) -> None:
    """种子数据：1 个项目 / 2 个章节（一个空章节）/ 2 个镜头 / 4 个候选。"""
    db.add_all(
        [
            _project(),
            Chapter(id="c1", project_id="p1", index=1, title="第一章"),
            Chapter(id="c-empty", project_id="p1", index=2, title="空章节"),
            Shot(id="s1", chapter_id="c1", index=1, title="镜头一"),
            Shot(id="s2", chapter_id="c1", index=2, title="镜头二"),
            _candidate(
                "s1",
                ShotCandidateType.character,
                "小雨",
                payload={"description": "25岁互联网运营", "voice_description": "青年女声"},
            ),
            _candidate("s1", ShotCandidateType.scene, "出租屋"),
            _candidate("s2", ShotCandidateType.character, "小雨"),
            _candidate("s2", ShotCandidateType.prop, "欠条"),
        ]
    )


async def _seed_empty_chapter(db: AsyncSession) -> None:
    """种子数据：只有一个不含镜头的章节。"""
    db.add_all([_project(), Chapter(id="c-empty", project_id="p1", index=1, title="空章节")])


def _use_env(env: _DbEnv) -> None:
    """把会话环境挂到 `get_db` 覆盖上。"""
    app.dependency_overrides[get_db] = env.override


def _clear_env() -> None:
    app.dependency_overrides.clear()


def test_batch_create_assets_route_returns_real_envelope_shape(
    client: TestClient,
) -> None:
    """C-18：路由级断言真实响应形状 —— data 是 {created, linked, skipped} 三个列表。

    这条用例替代「直调 service 后断言 list 长度」的旧口径：如果 service 返回值与
    路由 `response_model=ApiResponse[dict[str, Any]]` 不符，响应会直接 500。
    """
    env = _make_env(_seed_full_graph)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"chapter_id": "c1"})
    finally:
        _clear_env()

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["message"] == "success"
    assert body["meta"] is None
    data = body["data"]
    # 真实形状：dict（而非被错误包裹的单元素 list）
    assert isinstance(data, dict)
    # 契约：三个建实体计数 + 两个「角色→服装自动绑定」的第二遍结果。
    assert set(data) == {"created", "linked", "skipped", "costume_bound", "costume_unbound"}
    assert all(isinstance(data[key], list) for key in data)
    assert [item["name"] for item in data["created"]] == ["小雨", "出租屋", "欠条"]
    # s2 的「小雨」与 s1 同名 → 复用已创建实体，走 linked 而不是重复新建
    assert [item["name"] for item in data["linked"]] == ["小雨"]
    assert data["skipped"] == []
    assert data["created"][0]["entity_id"]
    assert data["created"][0]["type"] == "character"

    async def _count_characters() -> int:
        return len(list((await env.session.execute(select(Character))).scalars().all()))

    assert env.run(_count_characters()) == 1


def test_batch_create_assets_route_empty_chapter_returns_empty_lists(
    client: TestClient,
) -> None:
    """C-18 边界：空章节（无镜头）也必须返回 200 + 三个空列表，而不是报错。"""
    env = _make_env(_seed_empty_chapter)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"chapter_id": "c-empty"})
    finally:
        _clear_env()

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"] == {"created": [], "linked": [], "skipped": []}


def test_batch_create_assets_route_unknown_chapter_returns_404(client: TestClient) -> None:
    """边界：章节不存在 → 404（ValueError 以 ` not found` 结尾的错误壳）。"""
    env = _make_env(_seed_full_graph)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"chapter_id": "nope"})
    finally:
        _clear_env()

    assert response.status_code == 404
    assert response.json() == {
        "code": 404,
        "message": "Chapter not found",
        "data": None,
        "meta": None,
    }


def test_batch_create_assets_route_invalid_types_returns_400(client: TestClient) -> None:
    """C-18 边界：非法 types → 400 错误壳（而不是 500）。"""
    env = _make_env(_seed_full_graph)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"chapter_id": "c1", "types": ["unknown"]})
    finally:
        _clear_env()

    assert response.status_code == 400
    assert response.json() == {
        "code": 400,
        "message": "unsupported candidate types: ['unknown']",
        "data": None,
        "meta": None,
    }


def test_batch_create_assets_route_empty_types_processes_nothing(client: TestClient) -> None:
    """D-11：显式传 `types=[]` 表示「一个都不处理」，与 `types=None`（全部）区分。

    修复前 `types=[]` 会走 `(types or [])` 被当成「不限定＝全部」，把 4 个候选全部处理掉。
    """
    env = _make_env(_seed_full_graph)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"chapter_id": "c1", "types": []})
        # 对照组：不传 types 时应当处理全部候选（旧行为对 None 是正确的）
        all_types_response = client.post(ENDPOINT, json={"chapter_id": "c1"})
    finally:
        _clear_env()

    assert response.status_code == 200
    assert response.json()["data"] == {"created": [], "linked": [], "skipped": []}

    assert all_types_response.status_code == 200
    assert len(all_types_response.json()["data"]["created"]) == 3


def test_batch_create_assets_route_rejects_too_many_types(client: TestClient) -> None:
    """C-18 边界（超限）：types 超过 schema `max_length=4` → 422 校验失败。"""
    env = _make_env(_seed_full_graph)
    _use_env(env)
    try:
        response = client.post(
            ENDPOINT,
            json={"chapter_id": "c1", "types": ["character", "scene", "prop", "costume", "character"]},
        )
    finally:
        _clear_env()

    assert response.status_code == 422
    assert response.json()["code"] == 422


def test_batch_create_assets_route_midway_failure_keeps_processing_rest(
    client: TestClient, monkeypatch
) -> None:
    """C-14：某个候选 flush 失败后，其余候选仍必须被正常处理（SAVEPOINT 隔离）。

    构造方式：让「a-会失败的道具」在 `db.flush()` 时触发真实的主键冲突（IntegrityError），
    复现 `create_entity` 内部 flush 失败把 session 打成 failed 态的场景。
    修复前：该候选之后的所有候选都会抛 `PendingRollbackError`，被整体误记为 skipped，而且
    失败候选的实体（SAVEPOINT 未回滚）会残留在会话里。
    """
    original = svc._create_entity_from_candidate

    async def _failing_create(db, *, entity_type, project_id, name, payload, chapter_id, shot_id):
        if name == "a-会失败的道具":
            # 真实 flush 失败：主键冲突（p1 已存在）
            db.add(_project("p1", "重复项目"))
            await db.flush()
        return await original(
            db,
            entity_type=entity_type,
            project_id=project_id,
            name=name,
            payload=payload,
            chapter_id=chapter_id,
            shot_id=shot_id,
        )

    monkeypatch.setattr(svc, "_create_entity_from_candidate", _failing_create)

    async def _seed_midway_failure(db: AsyncSession) -> None:
        await _seed_full_graph(db)
        db.add_all(
            [
                _candidate("s1", ShotCandidateType.prop, "a-会失败的道具"),
                _candidate("s1", ShotCandidateType.prop, "b-其后仍应创建的道具"),
                _candidate("s1", ShotCandidateType.prop, "c-其后仍应创建的道具"),
            ]
        )

    env = _make_env(_seed_midway_failure)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"chapter_id": "c1", "types": ["prop"]})
    finally:
        _clear_env()

    assert response.status_code == 200
    data = response.json()["data"]
    # 只有失败的那个候选进 skipped；失败原因来自真实的 flush 异常
    assert [item["name"] for item in data["skipped"]] == ["a-会失败的道具"]
    assert data["skipped"][0]["reason"]
    # 其余候选照常创建 —— 这正是 PendingRollbackError 会破坏的行为
    assert sorted(item["name"] for item in data["created"]) == [
        "b-其后仍应创建的道具",
        "c-其后仍应创建的道具",
        "欠条",
    ]

    async def _failed_entity_absent() -> bool:
        stmt = select(Prop).where(Prop.name == "a-会失败的道具")
        return (await env.session.execute(stmt)).scalars().first() is None

    assert env.run(_failed_entity_absent())


def test_batch_create_assets_route_no_double_report_on_link_failure(
    client: TestClient, monkeypatch
) -> None:
    """C-13：实体已创建、但紧随其后的 `mark_linked_by_name` 失败时，不得「双报」。

    修复前 `created.append(...)` 在 try 内，except 又 append 到 skipped →
    同一个候选同时出现在 created 与 skipped，前端提示「新建 1 / 跳过 1」。
    """
    original_link = svc.mark_linked_by_name

    async def _failing_link(db, *, shot_id, candidate_type, candidate_name, linked_entity_id):
        if candidate_name == "a-双报候选":
            raise RuntimeError("mark_linked_by_name 失败")
        return await original_link(
            db,
            shot_id=shot_id,
            candidate_type=candidate_type,
            candidate_name=candidate_name,
            linked_entity_id=linked_entity_id,
        )

    monkeypatch.setattr(svc, "mark_linked_by_name", _failing_link)

    async def _seed_link_failure(db: AsyncSession) -> None:
        await _seed_full_graph(db)
        db.add_all(
            [
                _candidate("s1", ShotCandidateType.prop, "a-双报候选"),
                _candidate("s1", ShotCandidateType.prop, "b-正常候选"),
            ]
        )

    env = _make_env(_seed_link_failure)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"chapter_id": "c1", "types": ["prop"]})
    finally:
        _clear_env()

    assert response.status_code == 200
    data = response.json()["data"]
    created_names = [item["name"] for item in data["created"]]
    linked_names = [item["name"] for item in data["linked"]]
    skipped_names = [item["name"] for item in data["skipped"]]

    assert skipped_names == ["a-双报候选"]
    assert "a-双报候选" not in created_names
    assert "a-双报候选" not in linked_names
    assert sorted(created_names) == ["b-正常候选", "欠条"]
    assert linked_names == []


def test_batch_create_assets_route_duplicate_submit_is_idempotent(client: TestClient) -> None:
    """C-18 边界（重复提交）：第二次提交不重复建实体，候选已 linked 故不再处理。"""
    env = _make_env(_seed_full_graph)
    _use_env(env)
    try:
        first = client.post(ENDPOINT, json={"chapter_id": "c1"})
        second = client.post(ENDPOINT, json={"chapter_id": "c1"})
    finally:
        _clear_env()

    assert first.status_code == 200
    assert len(first.json()["data"]["created"]) == 3

    assert second.status_code == 200
    assert second.json()["data"] == {
        "created": [],
        "linked": [],
        "skipped": [],
        "costume_bound": [],
        "costume_unbound": [],
    }

    async def _assert_single_character() -> int:
        return len(list((await env.session.execute(select(Character))).scalars().all()))

    assert env.run(_assert_single_character()) == 1


@pytest.mark.parametrize("chapter_id", ["c1"])
def test_batch_create_assets_route_requires_chapter_id(client: TestClient, chapter_id: str) -> None:
    """边界：缺 chapter_id → 422 校验失败（不进入 service）。"""
    env = _make_env(_seed_full_graph)
    _use_env(env)
    try:
        response = client.post(ENDPOINT, json={"types": ["character"]})
    finally:
        _clear_env()

    assert response.status_code == 422
    assert response.json()["code"] == 422
