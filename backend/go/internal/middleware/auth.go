package middleware

import (
	"context"
	"net/http"
	"strings"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/auth"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/response"
)

// userIDKey 是 context 中保存已认证用户 ID 的私有键。
type userIDKey struct{}

// UserIDFromContext 取出已认证用户 ID。
func UserIDFromContext(ctx context.Context) (int, bool) {
	id, ok := ctx.Value(userIDKey{}).(int)
	return id, ok
}

// RequireAuth 校验 Authorization: Bearer 令牌。
//
// 失败语义与 Python 完全一致（这是前端「自动跳登录页」依赖的契约）：
//   - 缺令牌 / 令牌非法 / 已过期 → 401 + `WWW-Authenticate: Bearer`
//   - 响应体是同一个 `{code,message,data,meta}` 信封
func RequireAuth(secret string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			header := r.Header.Get("Authorization")
			if !strings.HasPrefix(strings.ToLower(header), "bearer ") {
				unauthorized(w)
				return
			}
			token := strings.TrimSpace(header[len("bearer "):])
			if token == "" {
				unauthorized(w)
				return
			}

			claims, err := auth.ParseToken(secret, token)
			if err != nil {
				unauthorized(w)
				return
			}

			ctx := context.WithValue(r.Context(), userIDKey{}, claims.UserID)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// unauthorized 写出与 Python 一致的 401。
func unauthorized(w http.ResponseWriter) {
	w.Header().Set("WWW-Authenticate", "Bearer")
	response.WriteError(w, http.StatusUnauthorized, "未登录，请先登录")
}
