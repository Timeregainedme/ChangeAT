// Package middleware 提供控制面的通用中间件。
package middleware

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net/http"
	"time"
)

// requestIDKey 是 context 中保存请求 ID 的私有键类型，避免与其他包的键冲突。
type requestIDKey struct{}

// RequestIDHeader 与 Python 侧的约定保持一致，便于 Nginx 日志与审计表关联。
const RequestIDHeader = "X-Request-ID"

// RequestID 为每个请求补齐 X-Request-ID。
//
// 优先复用上游带来的 ID（Nginx 或调用方生成），这样「一次用户操作」在
// Nginx 日志、Go 日志、Python 日志里是同一个值；缺省时生成一个短随机串。
func RequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get(RequestIDHeader)
		if id == "" {
			id = newRequestID()
		}
		w.Header().Set(RequestIDHeader, id)
		ctx := context.WithValue(r.Context(), requestIDKey{}, id)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// RequestIDFromContext 取出请求 ID，缺失时返回空串。
func RequestIDFromContext(ctx context.Context) string {
	if id, ok := ctx.Value(requestIDKey{}).(string); ok {
		return id
	}
	return ""
}

// newRequestID 生成 16 位十六进制随机串。
//
// 不用 UUID 的原因：这里只用于日志关联，16 位随机足以避免同日碰撞，
// 且比 36 字符的 UUID 更短、更易在日志里肉眼比对。
func newRequestID() string {
	buf := make([]byte, 8)
	if _, err := rand.Read(buf); err != nil {
		// 随机源不可用时退化为时间戳，宁可 ID 可预测也不能让请求失败。
		return time.Now().UTC().Format("20060102150405.000000")
	}
	return hex.EncodeToString(buf)
}

// statusRecorder 记录响应状态码，供访问日志使用。
type statusRecorder struct {
	http.ResponseWriter
	status int
	bytes  int
}

func (s *statusRecorder) WriteHeader(status int) {
	s.status = status
	s.ResponseWriter.WriteHeader(status)
}

func (s *statusRecorder) Write(b []byte) (int, error) {
	if s.status == 0 {
		s.status = http.StatusOK
	}
	n, err := s.ResponseWriter.Write(b)
	s.bytes += n
	return n, err
}

// AccessLog 用 slog 输出结构化访问日志。
//
// 只记录方法、路径、状态码、耗时与请求 ID。**不记录 query 与请求头**：
// 下载链接的签名参数、Authorization 头都属敏感信息，落进日志等于扩大泄露面。
func AccessLog(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			started := time.Now()
			rec := &statusRecorder{ResponseWriter: w}
			next.ServeHTTP(rec, r)

			status := rec.status
			if status == 0 {
				status = http.StatusOK
			}
			level := slog.LevelInfo
			if status >= 500 {
				level = slog.LevelError
			} else if status >= 400 {
				level = slog.LevelWarn
			}

			logger.LogAttrs(r.Context(), level, "http_request",
				slog.String("method", r.Method),
				slog.String("path", r.URL.Path),
				slog.Int("status", status),
				slog.Int("bytes", rec.bytes),
				slog.Duration("duration", time.Since(started)),
				slog.String("request_id", RequestIDFromContext(r.Context())),
			)
		})
	}
}

// Recover 捕获 panic，返回与 Python 侧一致的 500 信封。
//
// 为什么返回信封而不是裸露的 500：前端统一按 `message` 展示错误，
// 纯文本响应会让它显示成「未知错误」。
func Recover(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if rec := recover(); rec != nil {
					logger.Error("panic recovered",
						"path", r.URL.Path,
						"panic", rec,
						"request_id", RequestIDFromContext(r.Context()),
					)
					w.Header().Set("Content-Type", "application/json; charset=utf-8")
					w.WriteHeader(http.StatusInternalServerError)
					_, _ = w.Write([]byte(`{"code":500,"message":"Internal server error","data":null,"meta":null}`))
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}
