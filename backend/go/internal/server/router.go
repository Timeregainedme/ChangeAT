// Package server 组装路由。
package server

import (
	"database/sql"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/handler"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/middleware"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/proxy"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/store"
)

// Deps 是路由需要的依赖集合。
type Deps struct {
	Logger    *slog.Logger
	DB        *sql.DB
	JWTSecret string
	// PythonUpstream 用于「Go 未实现的分支」透传，如私有桶下的流式下载。
	PythonUpstream string
}

// NewRouter 构建控制面的 HTTP 路由。
//
// 路由分组刻意与 Python 侧平行：`/health`（根路径探活）与 `/api/v1/*`（业务）。
// 这样 Nginx 可以按前缀分流，且切换某一条路径时不影响其他路径。
//
// 切流原则：**只注册已经真正实现的路径**。
// 未接管的路径保持 404，让 Nginx 明确地把流量留给 Python；
// 若提前注册空 handler，前端会拿到 200 空壳并把它误读成「没有数据」。
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

		if deps.DB != nil {
			authHandler := handler.NewAuth(store.NewUserStore(deps.DB))

			taskHandler := handler.NewTask(
				store.NewTaskStore(deps.DB),
				store.NewWorkspaceStore(deps.DB),
			)

			projectHandler := handler.NewProject(
				store.NewProjectStore(deps.DB),
				store.NewWorkspaceStore(deps.DB),
			)
			chapterHandler := handler.NewChapter(
				store.NewChapterStore(deps.DB),
				store.NewWorkspaceStore(deps.DB),
			)

			// 受保护路由：与 Python 的 `/auth/me` 同契约。
			r.Group(func(r chi.Router) {
				r.Use(middleware.RequireAuth(deps.JWTSecret))
				r.Get("/auth/me", authHandler.Me)

				// 项目 / 章节只读。写操作（POST/PATCH/DELETE）仍留 Python：
				// 读错了最多是"看到错数据"，写错了是"写坏数据"，风险等级不同。
				r.Get("/studio/projects", projectHandler.List)
				// 必须显式声明：chi 的路由优先级里静态段高于参数段，
				// 但这里的顺序仍写在参数路由之前，避免读代码时误判。
				r.Get("/studio/projects/style-options", projectHandler.StyleOptions)
				r.Get("/studio/projects/{project_id}", projectHandler.Get)
				r.Get("/studio/chapters", chapterHandler.List)
				r.Get("/studio/chapters/{chapter_id}", chapterHandler.Get)

				// 任务状态与结果查询：前端任务中心的高频轮询入口。
				r.Get("/film/tasks/{task_id}/status", taskHandler.Status)
				r.Get("/film/tasks/{task_id}/result", taskHandler.Result)
			})

			// 公开路由：素材下载必须匿名可访问（浏览器 <img>/<video> 无法带 Authorization）。
			// 与 Python 的 public_router 一致，不挂 RequireAuth。
			fileHandler := handler.NewFile(
				store.NewFileStore(deps.DB),
				proxy.ToPython(deps.PythonUpstream),
			)
			r.Get("/studio/files/{file_id}/download", fileHandler.Download)
			r.Head("/studio/files/{file_id}/download", fileHandler.Download)
		}
	})

	return r
}
