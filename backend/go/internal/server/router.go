// Package server 组装路由。
package server

import (
	"database/sql"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/handler"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/middleware"
)

// Deps 是路由需要的依赖集合。
type Deps struct {
	Logger *slog.Logger
	DB     *sql.DB
}

// NewRouter 构建控制面的 HTTP 路由。
//
// 路由分组刻意与 Python 侧平行：`/health`（根路径探活）与 `/api/v1/*`（业务）。
// 这样 Nginx 可以按前缀分流，且切换某一条路径时不影响其他路径。
func NewRouter(deps Deps) http.Handler {
	r := chi.NewRouter()

	// 通用中间件：顺序即执行顺序（Recover 最外层，保证 panic 也被记录请求 ID）。
	r.Use(middleware.Recover(deps.Logger))
	r.Use(middleware.RequestID)
	r.Use(middleware.AccessLog(deps.Logger))

	health := handler.NewHealth(deps.DB)

	// 根路径探活：与 Python 的 GET /health 对齐，便于探针在切流前后无需改配置。
	r.Get("/health", health.Live)

	r.Route("/api/v1", func(r chi.Router) {
		// 与 Python 的 /api/v1/health 对齐（health.router 挂在 v1 下）。
		r.Get("/health", health.Live)
		// 切流专用的就绪探针，Python 侧没有对应实现，因此不改动既有契约。
		r.Get("/ready", health.Ready)
	})

	return r
}
