// Package handler 实现控制面已接管的接口。
//
// 当前阶段（P2-1）只接管健康检查：这是切流前唯一需要的「零风险验证点」——
// 它同时验证了路由、响应信封、日志与数据库连通性，而不触碰任何业务数据。
package handler

import (
	"database/sql"
	"net/http"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/response"
)

// Health 提供健康检查。
type Health struct {
	db *sql.DB
}

// NewHealth 构造健康检查 handler。db 可为 nil（尚未接数据库时）。
func NewHealth(db *sql.DB) *Health {
	return &Health{db: db}
}

// Live 返回进程存活状态。
//
// 语义只表示「进程还在跑」，不查数据库：存活探针若依赖外部组件，
// 数据库抖动会导致进程被误杀重启，反而放大故障。
func (h *Health) Live(w http.ResponseWriter, r *http.Request) {
	response.WriteSuccess(w, map[string]string{"status": "ok"})
}

// Ready 返回「可以接收业务流量」的状态。
//
// 与 Live 的区别：这里会真正 Ping 数据库。切流后 Nginx 用 Ready 判断是否
// 把请求转给 Go —— 数据库不可用时应该让流量留在 Python 侧，而不是让用户看到 500。
func (h *Health) Ready(w http.ResponseWriter, r *http.Request) {
	if h.db == nil {
		response.WriteError(w, http.StatusServiceUnavailable, "database not configured")
		return
	}
	if err := h.db.PingContext(r.Context()); err != nil {
		response.WriteError(w, http.StatusServiceUnavailable, "database unavailable")
		return
	}
	response.WriteSuccess(w, map[string]string{"status": "ok", "database": "ok"})
}
