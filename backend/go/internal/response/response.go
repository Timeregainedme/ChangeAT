// Package response 定义与 Python 后端一致的响应信封。
package response

import (
	"encoding/json"
	"net/http"
)

// Envelope 是与 Python 后端逐字段一致的响应信封。
//
// 为什么必须自己定义一个结构体而不是直接 `json.Marshal(map)`：
// 前端只认 `{code, message, data, meta}` 这个形状（`ApiResponse`），
// 任何字段名/层级变化都会让所有页面的错误处理失效。
// 用结构体可以把「字段名」固定成编译期常量，避免手写 map 时拼错。
type Envelope struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data"`
	Meta    any    `json:"meta"`
}

// Success 返回 code=200 的成功响应。
func Success(data any) Envelope {
	return Envelope{Code: http.StatusOK, Message: "success", Data: data, Meta: nil}
}

// Error 返回与 HTTP 状态码一致的业务码。
//
// 与 Python 侧的约定保持一致：`code` 等于 HTTP status，`message` 是可直接展示的文案，
// `data` 恒为 null。前端据此把 message 塞进提示条。
func Error(status int, message string) Envelope {
	return Envelope{Code: status, Message: message, Data: nil, Meta: nil}
}

// WriteJSON 以指定状态码写出信封。
func WriteJSON(w http.ResponseWriter, status int, body Envelope) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// WriteSuccess 写出 200 成功响应。
func WriteSuccess(w http.ResponseWriter, data any) {
	WriteJSON(w, http.StatusOK, Success(data))
}

// WriteError 写出错误响应，HTTP 状态与业务码一致。
func WriteError(w http.ResponseWriter, status int, message string) {
	WriteJSON(w, status, Error(status, message))
}
