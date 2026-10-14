"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import router as api_v1_router
from app.bootstrap import bootstrap_all_registries
from app.config import settings
from app.schemas.common import ApiResponse


def _error_message(detail: object) -> str:
    """将异常 detail 转为前端可读的 message。"""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict) and "msg" in item:
                loc = item.get("loc", ())
                loc_str = ".".join(str(x) for x in loc if x != "body")
                parts.append(f"{loc_str}: {item['msg']}" if loc_str else item["msg"])
            else:
                parts.append(str(item))
        return "; ".join(parts) if parts else "Validation error"
    return str(detail)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """HTTP 异常统一为 { code, message, data: null }。

    需转发 ``exc.headers``：FastAPI 默认处理器会带上它们，而自定义处理器若丢弃，
    依赖响应头表达语义的状态码就失效（如 416 的 ``Content-Range: bytes */total``）。
    """
    if isinstance(exc, HTTPException):
        code = exc.status_code
        message = _error_message(exc.detail)
        headers = exc.headers
    else:
        code = 500
        message = "Internal server error"
        headers = None
    body = ApiResponse[None](code=code, message=message, data=None, meta=None).model_dump()
    return JSONResponse(status_code=code, content=body, headers=headers)


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """422 校验异常统一为 { code: 422, message, data: null }。"""
    assert isinstance(exc, RequestValidationError)
    message = _error_message(exc.errors())
    body = ApiResponse[None](code=422, message=message, data=None, meta=None).model_dump()
    return JSONResponse(status_code=422, content=body)


async def value_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """ValueError 统一为 { code, message, data: null }。

    服务层约定（`app.services.common.errors.entity_not_found`）：
    - 消息以 ` not found` 结尾的 ValueError 表示实体不存在 → 404；
    - 其余 ValueError 表示请求参数/状态非法（如 "ratio is required"）→ 400。

    此前未注册 ValueError handler，此类异常会落到通用 Exception handler 变成
    500 Internal server error，使「缺项」被误报为服务端故障（评审 R-10）。
    """
    message = _error_message(str(exc))
    code = 404 if message.endswith(" not found") else 400
    body = ApiResponse[None](code=code, message=message, data=None, meta=None).model_dump()
    return JSONResponse(status_code=code, content=body)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化，关闭时清理。"""
    # 启动时：供应商注册 + 任务执行器注册（幂等）
    bootstrap_all_registries()
    yield
    # 关闭时：清理资源
    pass


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# 统一错误响应格式：{ code, message, data: null }
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(ValueError, value_error_handler)
app.add_exception_handler(Exception, http_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
# 影视技能路由同时挂到主应用，保证 /api/v1/film 一定可访问


@app.get("/health")
async def health():
    """健康检查。"""
    from app.schemas.common import success_response
    return success_response({"status": "ok"})
