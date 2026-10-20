"""Pytest 共享 fixture：FastAPI 应用与 TestClient。"""

from __future__ import annotations

import asyncio
import inspect
import os
from types import SimpleNamespace

# 必须在导入 app 之前设置：`app.config.settings` 是模块级单例，import 时即固化。
# 敏感字段加密（app/core/crypto.py）在既无 SECRETS_KEY 又无 JWT_SECRET 时会拒绝工作，
# 而本仓库不提交 backend/.env，因此测试环境在这里注入一个固定密钥。
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")

import pytest
from fastapi.testclient import TestClient

try:
    from app.main import app  # type: ignore

    from app.models.types import WorkspaceRole
except Exception:  # noqa: BLE001
    # 测试环境里有些可选依赖（例如 langgraph）可能未安装。
    # 不要让整个测试套件在导入 conftest 时直接失败；仅在需要 client 的测试里跳过。
    app = None


@pytest.fixture
def client() -> TestClient:
    """FastAPI 应用 TestClient，用于集成测试。"""
    if app is None:
        pytest.skip("FastAPI app 依赖未满足（例如缺少 langgraph），跳过需要 client 的集成测试。")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_route_auth():
    """默认放行路由级鉴权，让接口测试只关注响应壳。

    为什么需要：`app/api/v1/__init__.py` 给所有业务路由统一挂了
    `require_auth` 依赖，而绝大多数接口测试只验证 `{code, message, data}`
    信封，并不关心登录态。若每个用例各自准备 token，会让测试与被测逻辑
    一起漂移（本次 121 个用例正是因为契约升级后集体 401）。

    需要验证「未登录」行为的用例，可在用例外显式覆盖：

        app.dependency_overrides.pop(require_auth, None)

    autouse 的作用域限制：仅在用例执行期间生效，结束后恢复原状，不影响
    其他用例对鉴权的断言。
    """
    if app is None:
        yield
        return

    from app import dependencies

    fake_user = SimpleNamespace(
        id=1,
        username="test-user",
        display_name="测试用户",
        is_active=True,
        auth_provider="local",
    )
    # 工作区上下文同样默认放行：同名项目 ID 在测试里被大量复用，
    # 若走真实解析（查询 workspace_members）会因测试库没有成员行而全部 403。
    # 需要验证多租户隔离的用例，应显式 pop 本覆盖并用真实 DB 断言。
    fake_ctx = dependencies.WorkspaceContext(
        workspace_id="ws-test",
        user_id=1,
        role=WorkspaceRole.editor,
    )
    app.dependency_overrides[dependencies.require_auth] = lambda: fake_user
    app.dependency_overrides[dependencies.get_workspace_context] = lambda: fake_ctx
    try:
        yield
    finally:
        app.dependency_overrides.pop(dependencies.require_auth, None)
        app.dependency_overrides.pop(dependencies.get_workspace_context, None)


def pytest_configure(config: pytest.Config) -> None:
    """为轻量测试环境补齐 asyncio marker。"""
    config.addinivalue_line("markers", "asyncio: mark test as asyncio coroutine")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """在未安装 pytest-asyncio 的环境中兜底执行 async 测试。"""

    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None

    funcargs = {
        arg: pyfuncitem.funcargs[arg]
        for arg in pyfuncitem._fixtureinfo.argnames
        if arg in pyfuncitem.funcargs
    }
    asyncio.run(pyfuncitem.obj(**funcargs))
    return True
