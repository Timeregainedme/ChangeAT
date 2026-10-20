"""FastAPI 依赖注入。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.core.security import decode_access_token
from app.models.auth import User
from app.models.types import WorkspaceRole
from app.models.workspace import Workspace, WorkspaceMember
from app.services.llm.resolver import build_default_text_llm

# auto_error=False：缺 Authorization 头时返回 None 而不是直接 403，
# 便于我们统一返回 401 + WWW-Authenticate（语义更准确）。
bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """提供异步数据库会话。"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> "User":
    """从 Authorization: Bearer 解析并返回当前用户。

    失败语义：
    - 缺 token / token 非法 → 401
    - 用户不存在 / 已停用 → 401（不区分，避免账号枚举）
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录，请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态无效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(sub)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态无效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态无效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_auth(user: "User" = Depends(get_current_user)) -> "User":
    """路由级保护依赖：挂在 router 上即要求登录。"""
    return user


# 工作区上下文通过请求头传递，而不是塞进 URL：
# - 避免给 119 个路径批量加路径参数，前端只需设一个全局头；
# - 与「项目归属哪个工作区」解耦，同一项目 ID 不会被拼进另一个租户的 URL 里。
WORKSPACE_HEADER = "X-Workspace-ID"

# 角色能力矩阵。数值越大权限越高，`require_workspace_role` 按「最低等级」判断。
_ROLE_LEVEL: dict[WorkspaceRole, int] = {
    WorkspaceRole.viewer: 1,
    WorkspaceRole.editor: 2,
    WorkspaceRole.admin: 3,
    WorkspaceRole.owner: 4,
}


@dataclass(frozen=True)
class WorkspaceContext:
    """一次请求所处的工作区上下文。

    为什么单独成对象而不是直接传 `workspace_id` 字符串：
    写操作需要同时知道「是谁、在哪个工作区、是什么角色」，三个值分开传容易漏。
    """

    workspace_id: str
    user_id: int
    role: WorkspaceRole

    @property
    def level(self) -> int:
        """角色权限等级，用于比较。"""
        return _ROLE_LEVEL.get(self.role, 0)

    @property
    def can_write(self) -> bool:
        """是否具备内容写权限（editor 及以上）。

        viewer 只读的设计意图：外部审片 / 甲方预览账号不应该能触发模型生成，
        因为生成会真实消耗供应商额度。
        """
        return self.level >= _ROLE_LEVEL[WorkspaceRole.editor]


async def get_workspace_context(
    request: Request,
    user: "User" = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceContext:
    """解析当前请求所属的工作区与成员角色。

    解析优先级：
    1. 请求头 `X-Workspace-ID`；
    2. 路径参数 `workspace_id`（为将来 REST 风格路由预留）；
    3. 都没有时，取该用户加入的第一个工作区 —— 单工作区用户（当前全部存量用户）
       无需任何前端改动即可继续工作。

    失败语义（刻意统一为 404，避免枚举）：
    - 工作区不存在、已停用、或用户不是其成员 → 一律 404「工作区不存在」；
    - 用户不属于任何工作区 → 403，这是「账号没被分配」而非「资源不存在」。
    """
    requested_id = request.headers.get(WORKSPACE_HEADER) or request.path_params.get("workspace_id")

    if requested_id:
        member = await db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == requested_id,
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.is_active.is_(True),
            )
        )
        workspace = await db.get(Workspace, requested_id)
        if member is None or workspace is None or not workspace.is_active:
            # 不区分「不存在」与「无权访问」，防止通过 403/404 差异探测工作区。
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="工作区不存在",
            )
        return WorkspaceContext(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole(member.role),
        )

    member = await db.scalar(
        select(WorkspaceMember)
        .where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.is_active.is_(True),
        )
        .order_by(WorkspaceMember.id)
        .limit(1)
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号未加入任何工作区，请联系管理员",
        )
    return WorkspaceContext(
        workspace_id=member.workspace_id,
        user_id=user.id,
        role=WorkspaceRole(member.role),
    )


def require_workspace_role(minimum: WorkspaceRole):
    """生成「至少具备某角色」的依赖。

    用法：写操作路由参数声明 `_ctx: WorkspaceContext = Depends(require_workspace_role(WorkspaceRole.editor))`。
    读操作直接依赖 `get_workspace_context` 即可。
    """

    async def _checker(
        ctx: WorkspaceContext = Depends(get_workspace_context),
    ) -> WorkspaceContext:
        if ctx.level < _ROLE_LEVEL[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"当前角色（{ctx.role.value}）无此操作权限，至少需要 {minimum.value}",
            )
        return ctx

    return _checker


# 常用角色门禁，避免每处各写一遍工厂调用。
require_viewer = require_workspace_role(WorkspaceRole.viewer)
require_editor = require_workspace_role(WorkspaceRole.editor)
require_admin = require_workspace_role(WorkspaceRole.admin)
require_owner = require_workspace_role(WorkspaceRole.owner)


async def get_llm(db: AsyncSession = Depends(get_db)) -> BaseChatModel:
    """提供默认文本 LLM（ChatOpenAI）。"""
    return await build_default_text_llm(db, thinking=True)

async def get_nothinking_llm(db: AsyncSession = Depends(get_db)) -> BaseChatModel:
    """提供默认文本 LLM（ChatOpenAI，禁用 thinking）。"""
    return await build_default_text_llm(db, thinking=False)


class _ImageHttpRunnable:
    """最小图片生成 runnable：从环境变量读取配置，通过 HTTP 调用外部图片生成服务。"""

    def __init__(self, *, base_url: str, api_key: str, timeout_s: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = timeout_s

    def invoke(self, payload: dict) -> dict:  # noqa: ANN001
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise HTTPException(status_code=503, detail="Install httpx to enable image generation") from e
        with httpx.Client(timeout=self._timeout_s) as client:
            r = client.post(
                self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {"images": data}

    async def ainvoke(self, payload: dict) -> dict:  # noqa: ANN001
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise HTTPException(status_code=503, detail="Install httpx to enable image generation") from e
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            r = await client.post(
                self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {"images": data}
