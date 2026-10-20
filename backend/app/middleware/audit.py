"""审计中间件：把写操作追加到 `audit_logs`。

三条硬约束（决定了实现形态）：

1. **不阻塞请求**。审计写库失败不能影响业务响应 —— 否则一次磁盘抖动会让全站写操作 500。
   这里用「独立 session + 异常吞掉只记日志」，并在响应发出前后各做一次时间记录。
2. **不复用请求 session**。业务事务可能因为异常回滚，而审计恰恰要记录被回滚的那次尝试。
   独立 session 才能保证「失败的操作也有记录」。
3. **不解析请求体**。`await request.body()` 会把上传的大文件读进内存，也会把
   `providers` 的 api_key、剧本正文一起带进审计表。这里只用路径与方法。

为什么身份解析要容错：
中间件在 FastAPI 依赖注入之前运行，拿不到 `get_current_user` 的结果。
这里直接解码 JWT 的 `sub`（不查库、不校验用户是否停用）：用户是否有效由路由层判定，
审计只负责「这条请求声称是谁发起的」。解析失败一律记 None，不阻断请求。
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.db import async_session_maker
from app.core.security import decode_access_token
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

ACTION_BY_METHOD = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}

# 路径形如 /api/v1/studio/projects/{id}/shots/{id}：
# 资源类型取「版本前缀之后的第一段」不够精确，这里取最后两段里能当类型的那一段。
_PATH_PREFIX_RE = re.compile(r"^/api/v1/")


def _split_resource(path: str) -> tuple[str | None, str | None]:
    """从路径推断资源类型与 ID。

    规则（够用即可，不做完整路由匹配）：
    - 去掉 `/api/v1/` 前缀；
    - 段数为偶数且末段看起来像 ID（UUID / 数字 / 长串）时，末段是 ID、倒数第二段是类型；
    - 否则末段是类型，无 ID（如 `/studio/projects` 列表、`/film/tasks` 创建）。
    """
    if not _PATH_PREFIX_RE.match(path):
        return None, None
    segments = [s for s in path[len("/api/v1/"):].split("/") if s]
    if not segments:
        return None, None

    last = segments[-1]
    looks_like_id = bool(re.fullmatch(r"[0-9]+|[0-9a-fA-F-]{16,}", last))
    if looks_like_id and len(segments) >= 2:
        return segments[-2], last
    return last, None


def _resolve_identity(request: Request) -> int | None:
    """从 Authorization 头解析操作者 ID（不校验有效性）。"""
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except Exception:  # noqa: BLE001 - 无效令牌不影响审计记录的其余字段
        return None
    sub = payload.get("sub")
    try:
        return int(sub)
    except (TypeError, ValueError):
        return None


class AuditLogMiddleware(BaseHTTPMiddleware):
    """为写操作追加审计记录。

    只处理 `/api/v1` 下的写请求；健康检查、静态资源、公开下载不记录。
    """

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        if request.method not in WRITE_METHODS or not _PATH_PREFIX_RE.match(request.url.path):
            return await call_next(request)

        started = time.perf_counter()
        status_code = 500
        error_detail: str | None = None
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:  # noqa: BLE001 - 记录后原样抛出，不改变业务语义
            error_detail = type(exc).__name__
            raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            await self._persist(
                request=request,
                status_code=status_code,
                duration_ms=duration_ms,
                error_detail=error_detail,
                request_id=response.headers.get("X-Request-ID") if response is not None else None,
            )

    async def _persist(
        self,
        *,
        request: Request,
        status_code: int,
        duration_ms: int,
        error_detail: str | None,
        request_id: str | None,
    ) -> None:
        """写入一条审计记录；任何异常只记日志，不影响响应。"""
        path = request.url.path
        resource_type, resource_id = _split_resource(path)
        workspace_id = request.headers.get("X-Workspace-ID") or None
        client_ip = request.client.host if request.client else None

        try:
            async with async_session_maker() as session:
                session.add(
                    AuditLog(
                        workspace_id=workspace_id,
                        user_id=_resolve_identity(request),
                        action=ACTION_BY_METHOD.get(request.method, "other"),
                        method=request.method,
                        path=path[:512],
                        resource_type=resource_type,
                        resource_id=resource_id,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        ip=(client_ip or "")[:64] or None,
                        user_agent=(request.headers.get("user-agent") or "")[:256] or None,
                        request_id=request_id or request.headers.get("X-Request-ID") or uuid.uuid4().hex,
                        detail=error_detail,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - 审计失败绝不能影响业务
            logger.warning("failed to persist audit log: path=%s", path, exc_info=True)
