"""API v1 路由聚合。

认证策略：
- `/health` 与 `/auth/*` 公开（健康检查用于探活，登录本身必须可匿名访问）。
- 其余业务路由统一挂 `require_auth` 依赖，未登录一律 401。
- Celery worker 内部不经过 HTTP，因此不受影响。
"""

from fastapi import APIRouter, Depends

from app.api.v1.routes import auth, film, health, llm, script_processing, studio
from app.api.v1.routes.studio import files as studio_files
from app.dependencies import require_auth

router = APIRouter()

# --- 公开路由 ---
router.include_router(health.router, tags=["health"])
router.include_router(auth.router, prefix="/auth", tags=["auth"])

# --- 受保护路由（需登录）---
_auth_only = [Depends(require_auth)]

router.include_router(film.router, prefix="/film", tags=["film"], dependencies=_auth_only)
router.include_router(llm.router, prefix="/llm", tags=["llm"], dependencies=_auth_only)
router.include_router(studio.router, prefix="/studio", dependencies=_auth_only)

# 素材下载保持匿名可访问（不从属于 studio 的鉴权依赖）。
# 原因：浏览器 <img>/<video> 无法携带 Authorization 头；素材本身位于
# 已配置公共读的对象存储，file_id 为不可枚举 UUID，匿名取用不比现状更不安全。
# 该路由会把请求 302 到对象存储公开 URL，不占用本机出网带宽。
router.include_router(studio_files.public_router, prefix="/studio/files", tags=["studio/files"])
router.include_router(script_processing.router, dependencies=_auth_only)
