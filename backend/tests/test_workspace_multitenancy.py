"""多租户隔离回归测试。

守护的核心性质（对应 backend-rewrite-plan.md §14 验收标准前两项）：
1. 同一账号在不同工作区里看到的是各自的项目，不会串；
2. 访问自己不是成员的工作区 → 404（而不是 403，避免把别家工作区 ID 变成可探测面）；
3. `viewer` 角色不能创建/修改项目，`editor` 可以；
4. 项目创建时 `workspace_id` / `created_by` 由服务端注入，客户端无法指定。

为什么必须用真实 DB 而不是替身：
隔离逻辑就是 SQL 层的一个 `WHERE workspace_id = ?`，替身无法证明这条 where 真的生效。
本文件因此自建 sqlite 内存库并通过 `dependency_overrides` 注入真实 session。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import dependencies
from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.auth import User
from app.models.studio import Project
from app.models.types import ProjectStyle, ProjectVisualStyle, WorkspaceRole
from app.models.workspace import Workspace, WorkspaceMember

PROJECTS_URL = "/api/v1/studio/projects"


async def _build_session() -> tuple[AsyncSession, object]:
    """建一个带全部表的 sqlite 内存库（连到同一个连接池以便共享 schema）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


def _make_project(project_id: str, workspace_id: str) -> Project:
    """构造一个最小可用项目。"""
    return Project(
        id=project_id,
        workspace_id=workspace_id,
        name=f"项目-{project_id}",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
        seed=0,
        unify_style=True,
        progress=0,
        use_dialog_audio_as_reference=True,
        stats={},
    )


@pytest.fixture
def seeded():
    """产出 (db, engine, client_factory) —— client_factory(user, workspace_header=None)。

    之所以用工厂：每个用例需要以不同身份、不同工作区上下文发请求，
    而 `dependency_overrides` 是全局挂在 app 上的，必须在用例内部切换。
    """
    import asyncio

    session_maker, engine = asyncio.run(_build_session())

    async def _seed() -> None:
        async with session_maker() as db:
            db.add_all(
                [
                    User(id=1, username="alice", display_name="Alice", is_active=True),
                    User(id=2, username="bob", display_name="Bob", is_active=True),
                    Workspace(id="ws-1", name="工作区一", slug="ws-1", owner_id=1, is_active=True),
                    Workspace(id="ws-2", name="工作区二", slug="ws-2", owner_id=2, is_active=True),
                    WorkspaceMember(workspace_id="ws-1", user_id=1, role=WorkspaceRole.owner),
                    WorkspaceMember(workspace_id="ws-2", user_id=2, role=WorkspaceRole.owner),
                    WorkspaceMember(workspace_id="ws-1", user_id=2, role=WorkspaceRole.viewer),
                    _make_project("proj-in-ws1", "ws-1"),
                    _make_project("proj-in-ws2", "ws-2"),
                ]
            )
            await db.commit()

    asyncio.run(_seed())

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_db

    # conftest 的 autouse fixture 默认放行了鉴权与工作区解析；
    # 本文件要验证真实隔离，必须撤销这两处覆盖。
    app.dependency_overrides.pop(dependencies.require_auth, None)
    app.dependency_overrides.pop(dependencies.get_workspace_context, None)

    def _client(user: User, workspace_id: str | None = None) -> TestClient:
        app.dependency_overrides[dependencies.get_current_user] = lambda: user
        client = TestClient(app)
        if workspace_id:
            client.headers[dependencies.WORKSPACE_HEADER] = workspace_id
        return client

    try:
        yield session_maker, engine, _client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(dependencies.get_current_user, None)
        asyncio.run(engine.dispose())


def test_project_list_only_returns_current_workspace(seeded) -> None:
    """列表必须按工作区过滤：alice 在 ws-1 看不到 ws-2 的项目。"""
    _session_maker, _engine, client_factory = seeded
    alice = User(id=1, username="alice", display_name="Alice", is_active=True)

    response = client_factory(alice, "ws-1").get(PROJECTS_URL)
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]["items"]]
    assert ids == ["proj-in-ws1"]


def test_cross_workspace_project_read_returns_404(seeded) -> None:
    """用 ws-2 的上下文读 ws-1 的项目必须是 404，且不能泄露「存在」这一事实。"""
    _session_maker, _engine, client_factory = seeded
    bob = User(id=2, username="bob", display_name="Bob", is_active=True)

    response = client_factory(bob, "ws-2").get(f"{PROJECTS_URL}/proj-in-ws1")
    assert response.status_code == 404
    assert response.json()["message"] == "Project not found"

    # 反向也要成立：bob 能在 ws-2 读到自己的项目
    ok = client_factory(bob, "ws-2").get(f"{PROJECTS_URL}/proj-in-ws2")
    assert ok.status_code == 200
    assert ok.json()["data"]["id"] == "proj-in-ws2"


def test_non_member_workspace_returns_404(seeded) -> None:
    """alice 不是 ws-2 的成员，带 ws-2 头访问必须 404，而不是「工作区不存在」以外的信息。"""
    _session_maker, _engine, client_factory = seeded
    alice = User(id=1, username="alice", display_name="Alice", is_active=True)

    response = client_factory(alice, "ws-2").get(PROJECTS_URL)
    assert response.status_code == 404
    assert response.json()["message"] == "工作区不存在"


def test_viewer_cannot_create_project(seeded) -> None:
    """bob 在 ws-1 是 viewer：可以看，不能建。"""
    _session_maker, _engine, client_factory = seeded
    bob = User(id=2, username="bob", display_name="Bob", is_active=True)

    payload = {
        "id": "proj-new",
        "name": "新项目",
        "style": ProjectStyle.real_people_city.value,
        "visual_style": ProjectVisualStyle.live_action.value,
    }
    response = client_factory(bob, "ws-1").post(PROJECTS_URL, json=payload)
    assert response.status_code == 403

    # 同一用户在 ws-2 是 owner，应当能建
    created = client_factory(bob, "ws-2").post(PROJECTS_URL, json=payload)
    assert created.status_code == 201
    assert created.json()["data"]["workspace_id"] == "ws-2"


def test_create_project_injects_workspace_and_creator(seeded) -> None:
    """workspace_id / created_by 由服务端注入，客户端传什么都应被忽略。"""
    _session_maker, _engine, client_factory = seeded
    alice = User(id=1, username="alice", display_name="Alice", is_active=True)

    payload = {
        "id": "proj-injected",
        "name": "注入校验",
        "style": ProjectStyle.real_people_city.value,
        "visual_style": ProjectVisualStyle.live_action.value,
        # 这两个字段不在 ProjectCreate 里，即便传了也不应生效
        "workspace_id": "ws-2",
        "created_by": 2,
    }
    response = client_factory(alice, "ws-1").post(PROJECTS_URL, json=payload)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["workspace_id"] == "ws-1"
    assert data["created_by"] == 1


def test_default_workspace_resolution_without_header(seeded) -> None:
    """不带 X-Workspace-ID 时回落到用户第一个工作区，保证存量单工作区用户无感。"""
    _session_maker, _engine, client_factory = seeded
    alice = User(id=1, username="alice", display_name="Alice", is_active=True)

    response = client_factory(alice).get(PROJECTS_URL)
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]["items"]]
    assert ids == ["proj-in-ws1"]


def test_user_without_workspace_gets_403(seeded) -> None:
    """没有加入任何工作区的账号必须得到明确提示，而不是空列表（空列表会被误读为「没数据」）。"""
    _session_maker, _engine, client_factory = seeded
    orphan = User(id=99, username="orphan", display_name="Orphan", is_active=True)

    response = client_factory(orphan).get(PROJECTS_URL)
    assert response.status_code == 403
    assert "未加入任何工作区" in response.json()["message"]
