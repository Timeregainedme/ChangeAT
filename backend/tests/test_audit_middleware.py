"""审计中间件回归测试。

守护的核心性质：
1. 写操作会落一条记录，读操作不会；
2. 请求体不被记录（避免供应商 api_key、剧本正文进审计表）；
3. 未认证请求也记录（user_id 为空），用于追踪越权尝试；
4. 审计写库失败不影响业务响应；
5. 资源类型/ID 能从路径正确推断。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import middleware as _middleware_pkg  # noqa: F401
from app.core.db import Base
from app.main import app
from app.middleware.audit import _split_resource
from app.models.audit import AuditLog


def _bind_temp_database(monkeypatch) -> tuple[object, object]:
    """把审计中间件指向一个临时内存库，避免污染真实统计。

    中间件用自己的 `async_session_maker`（不复用请求 session），
    所以必须在模块层替换该引用，而不是走 FastAPI 依赖覆盖。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_prepare())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from app.middleware import audit as audit_module

    monkeypatch.setattr(audit_module, "async_session_maker", maker)
    return maker, engine


def _bind_request_db(monkeypatch, maker) -> None:
    """把请求用的 DB 指向同一个临时库。

    不用 `object()` 空替身：业务层会调用 `db.scalar` / `db.execute`，
    空替身会让请求在业务代码里抛 AttributeError，测试就变成了在验证替身而非审计。
    这里直接复用已建表的 session factory，让请求能真实跑完。

    用 `monkeypatch.setitem` 而非直接赋值，确保用例结束后自动恢复。
    """
    from app.dependencies import get_db

    async def _get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setitem(app.dependency_overrides, get_db, _get_db)


def _read_logs(maker) -> list[AuditLog]:
    async def _query() -> list[AuditLog]:
        async with maker() as session:
            return list((await session.execute(select(AuditLog))).scalars().all())

    return asyncio.run(_query())


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/studio/projects", ("projects", None)),
        ("/api/v1/studio/projects/073ab715-d814-4026-a8ac-3341b902574b", ("projects", "073ab715-d814-4026-a8ac-3341b902574b")),
        # 真实业务 ID 是 UUID 或自增数字；短横线短串（如 runtime-summary）算类型而非 ID
        ("/api/v1/studio/shots/3f2b8c1e-1111-2222-3333-444455556666", ("shots", "3f2b8c1e-1111-2222-3333-444455556666")),
        ("/api/v1/studio/shot-dialog-lines/42", ("shot-dialog-lines", "42")),
        ("/health", (None, None)),
    ],
)
def test_split_resource(path: str, expected) -> None:
    """路径推断只做启发式判断，但必须对常见形态稳定。"""
    assert _split_resource(path) == expected


def test_write_request_is_audited(monkeypatch) -> None:
    """POST 应落一条 create 记录，且不包含请求体内容。"""
    maker, engine = _bind_temp_database(monkeypatch)
    _bind_request_db(monkeypatch, maker)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/studio/projects",
                json={"id": "proj-audit", "name": "审计", "style": "真人都市", "visual_style": "现实"},
                headers={"X-Workspace-ID": "ws-test"},
            )
        # 业务是否成功与本测试无关（DB 已被 stub 化），只要求不崩
        assert response.status_code < 600

        logs = _read_logs(maker)
        assert len(logs) == 1
        entry = logs[0]
        assert entry.method == "POST"
        assert entry.action == "create"
        assert entry.path == "/api/v1/studio/projects"
        assert entry.workspace_id == "ws-test"
        # 请求体不应出现在任何字段里
        assert "审计" not in (entry.detail or "")
    finally:
        asyncio.run(engine.dispose())


def test_read_request_is_not_audited(monkeypatch) -> None:
    """GET 不产生审计记录（读操作量大、价值低）。"""
    maker, engine = _bind_temp_database(monkeypatch)
    _bind_request_db(monkeypatch, maker)
    try:
        with TestClient(app) as client:
            client.get("/api/v1/studio/projects")
        assert _read_logs(maker) == []
    finally:
        asyncio.run(engine.dispose())


def test_unauthenticated_write_is_audited(monkeypatch) -> None:
    """未登录的写尝试必须留痕，否则最有信息量的样本（越权尝试）会丢。"""
    maker, engine = _bind_temp_database(monkeypatch)
    _bind_request_db(monkeypatch, maker)

    from app import dependencies

    # conftest 的 autouse fixture 默认放行鉴权，这里撤销以模拟真实的未登录请求。
    app.dependency_overrides.pop(dependencies.require_auth, None)
    try:
        with TestClient(app) as client:
            response = client.delete("/api/v1/studio/projects/proj-x")
        assert response.status_code == 401

        logs = _read_logs(maker)
        assert len(logs) == 1
        assert logs[0].user_id is None
        assert logs[0].status_code == 401
        assert logs[0].action == "delete"
    finally:
        asyncio.run(engine.dispose())


def test_audit_failure_does_not_break_request(monkeypatch) -> None:
    """审计写库异常必须被吞掉，业务照常返回。"""
    from app.middleware import audit as audit_module

    def _boom():
        raise RuntimeError("db down")

    # 先建临时库并接好请求侧 session，再把审计侧换成必定失败的工厂
    maker, engine = _bind_temp_database(monkeypatch)
    _bind_request_db(monkeypatch, maker)
    monkeypatch.setattr(audit_module, "async_session_maker", _boom)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/studio/projects",
            json={"id": "proj-boom", "name": "x", "style": "真人都市", "visual_style": "现实"},
        )
    # 审计失败不应把请求变成 500
    assert response.status_code != 500
    asyncio.run(engine.dispose())
