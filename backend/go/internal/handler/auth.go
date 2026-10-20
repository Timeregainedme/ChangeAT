package handler

import (
	"errors"
	"net/http"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/middleware"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/response"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/store"
)

// Auth 提供账号相关接口。
type Auth struct {
	users *store.UserStore
}

// NewAuth 构造 Auth handler。
func NewAuth(users *store.UserStore) *Auth {
	return &Auth{users: users}
}

// userRead 是 `UserRead` 的 Go 表示。
//
// 三个细节必须与 Python 一致，否则前端类型校验或展示会出问题：
//   - 可空字段用指针 + `omitempty`，序列化后是 null 或缺失；
//   - `created_at` 用 RFC3339 字符串（Python 的 datetime 默认序列化格式）；
//   - 字段顺序无关紧要，但字段名必须逐字一致。
type userRead struct {
	ID           int     `json:"id"`
	Username     string  `json:"username"`
	DisplayName  *string `json:"display_name"`
	IsActive     bool    `json:"is_active"`
	Email        *string `json:"email"`
	AvatarURL    *string `json:"avatar_url"`
	AuthProvider string  `json:"auth_provider"`
	CreatedAt    *string `json:"created_at"`
}

// Me 返回当前登录用户。
//
// 语义与 Python 的 `/api/v1/auth/me` 对齐：
//   - 令牌无效 → 401（由 RequireAuth 拦截，走不到这里）
//   - 用户已删除或已停用 → 401，而不是 200 + is_active=false。
//     原因：停用账号不应该能继续读写业务数据，前端看到 401 会回到登录页。
func (h *Auth) Me(w http.ResponseWriter, r *http.Request) {
	userID, ok := middleware.UserIDFromContext(r.Context())
	if !ok {
		response.WriteError(w, http.StatusUnauthorized, "未登录，请先登录")
		return
	}

	user, err := h.users.GetByID(r.Context(), userID)
	if errors.Is(err, store.ErrNotFound) {
		response.WriteError(w, http.StatusUnauthorized, "登录状态无效，请重新登录")
		return
	}
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取用户信息失败")
		return
	}
	if !user.IsActive {
		response.WriteError(w, http.StatusUnauthorized, "登录状态无效，请重新登录")
		return
	}

	var createdAt *string
	if user.CreatedAt != nil {
		// 必须与 Python 的 datetime.isoformat() 逐字节一致：
		// MySQL DATETIME 无时区，Python 读出来是 naive datetime，序列化后**不带** 时区后缀。
		// 若这里按 time.RFC3339 输出 "...Z"，前端 `new Date()` 会把它当 UTC，
		// 而 Python 的无后缀串会被当本地时间 —— 同一行数据在两个服务下差 8 小时。
		// `.999999` 让尾随零被省略，与 isoformat() 在微秒为 0 时不输出小数部分的行为对齐。
		formatted := user.CreatedAt.Format("2006-01-02T15:04:05.999999")
		createdAt = &formatted
	}

	response.WriteSuccess(w, userRead{
		ID:           user.ID,
		Username:     user.Username,
		DisplayName:  user.DisplayName,
		IsActive:     user.IsActive,
		Email:        user.Email,
		AvatarURL:    user.AvatarURL,
		AuthProvider: user.AuthProvider,
		CreatedAt:    createdAt,
	})
}
