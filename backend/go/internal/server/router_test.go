package server

import (
	"database/sql"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	_ "github.com/go-sql-driver/mysql"
)

// newTestRouter 构造一个不接数据库的路由，用于验证路由与响应信封。
func newTestRouter() http.Handler {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	return NewRouter(Deps{Logger: logger, DB: nil, JWTSecret: "test-secret"})
}

// decodeEnvelope 解出统一信封。
func decodeEnvelope(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var out map[string]any
	if err := json.Unmarshal(body, &out); err != nil {
		t.Fatalf("响应不是合法 JSON: %v (body=%s)", err, body)
	}
	return out
}

// TestHealthEnvelopeMatchesPython 锁定响应形状。
//
// 前端只认 `{code, message, data, meta}`；Go 接管的任何一条路径都必须逐字段一致，
// 否则切换后前端会把这几个接口当成「未知响应」。
func TestHealthEnvelopeMatchesPython(t *testing.T) {
	router := newTestRouter()

	for _, path := range []string{"/health", "/api/v1/health"} {
		t.Run(path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, path, nil)
			rec := httptest.NewRecorder()
			router.ServeHTTP(rec, req)

			if rec.Code != http.StatusOK {
				t.Fatalf("status = %d, want 200", rec.Code)
			}

			body := decodeEnvelope(t, rec.Body.Bytes())
			if body["code"].(float64) != 200 {
				t.Fatalf("code = %v, want 200", body["code"])
			}
			if body["message"] != "success" {
				t.Fatalf("message = %v, want success", body["message"])
			}
			// meta 必须存在且为 null —— Python 侧恒为 null，前端据此判断是否分页。
			if _, ok := body["meta"]; !ok {
				t.Fatal("响应缺少 meta 字段")
			}
			if body["meta"] != nil {
				t.Fatalf("meta = %v, want null", body["meta"])
			}
			data, ok := body["data"].(map[string]any)
			if !ok {
				t.Fatalf("data 不是对象: %v", body["data"])
			}
			if data["status"] != "ok" {
				t.Fatalf("data.status = %v, want ok", data["status"])
			}
		})
	}
}

// TestReadyWithoutDatabaseReturns503 验证就绪探针在无数据库时拒绝流量。
//
// 切流后 Nginx 依赖这条探针决定是否把请求转给 Go；
// 返回 200 会让流量进入一个查不了库的进程。
func TestReadyWithoutDatabaseReturns503(t *testing.T) {
	router := newTestRouter()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/ready", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
	body := decodeEnvelope(t, rec.Body.Bytes())
	if body["code"].(float64) != 503 {
		t.Fatalf("code = %v, want 503", body["code"])
	}
	if body["data"] != nil {
		t.Fatalf("data = %v, want null", body["data"])
	}
}

// TestRequestIDHeaderIsEchoed 验证上游带来的请求 ID 会被透传。
//
// Nginx 与审计表都依赖这个头做关联；Go 覆盖成新值会让链路断开。
func TestRequestIDHeaderIsEchoed(t *testing.T) {
	router := newTestRouter()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	req.Header.Set("X-Request-ID", "trace-abc")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if got := rec.Header().Get("X-Request-ID"); got != "trace-abc" {
		t.Fatalf("X-Request-ID = %q, want trace-abc", got)
	}
}

// TestUnknownPathReturns404 验证未接管路径不返回成功。
//
// 切流阶段最危险的失败模式是「路径没接管却回了 200 空壳」——
// 前端会把它当成「没有数据」而不是「服务不可用」。
func TestUnknownPathReturns404(t *testing.T) {
	router := newTestRouter()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/studio/projects", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

// TestNotFoundAndMethodNotAllowedUseEnvelope 锁定 404/405 的信封格式。
//
// chi 默认分别返回纯文本与空 body，前端按 {code,message} 解析会拿到 undefined。
// Python 侧踩过同一个坑（只注册了 FastAPI 的子类异常，捕获不到 Starlette 的 404），
// 这里两边都必须用同一套信封。
func TestNotFoundAndMethodNotAllowedUseEnvelope(t *testing.T) {
	router := newTestRouter()

	t.Run("404", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/definitely-not-a-route", nil)
		rec := httptest.NewRecorder()
		router.ServeHTTP(rec, req)

		if rec.Code != http.StatusNotFound {
			t.Fatalf("status = %d, want 404", rec.Code)
		}
		body := decodeEnvelope(t, rec.Body.Bytes())
		if body["code"].(float64) != 404 {
			t.Fatalf("code = %v, want 404", body["code"])
		}
		if body["data"] != nil {
			t.Fatalf("data = %v, want null", body["data"])
		}
	})

	t.Run("405", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodDelete, "/health", nil)
		rec := httptest.NewRecorder()
		router.ServeHTTP(rec, req)

		if rec.Code != http.StatusMethodNotAllowed {
			t.Fatalf("status = %d, want 405", rec.Code)
		}
		body := decodeEnvelope(t, rec.Body.Bytes())
		if body["code"].(float64) != 405 {
			t.Fatalf("code = %v, want 405", body["code"])
		}
	})
}

// TestMethodNotAllowedFallsBackToPython 锁定「写方法回落 Python」的行为。
//
// 背景：Nginx 的 `location = /api/v1/studio/projects` 只匹配路径、不区分方法，
// 所以 POST 也会被转到 Go。而 Go 只接管了 GET —— 若不回落，用户点「创建项目」
// 会直接收到 405。这条测试防止有人把 MethodNotAllowed 改回纯 405。
func TestMethodNotAllowedFallsBackToPython(t *testing.T) {
	// 起一个假的 Python 上游：任何请求都回 201 + 固定 body
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"code":201,"message":"from-python","data":null,"meta":null}`))
	}))
	defer upstream.Close()

	// 需要非 nil 的 *sql.DB 才会注册受保护路由；用懒连接的空库，
	// 请求在 MethodNotAllowed 阶段就被拦截，不会真的查库。
	stubDB, err := sql.Open("mysql", "u:p@tcp(127.0.0.1:1)/none")
	if err != nil {
		t.Fatalf("构造 stub DB 失败: %v", err)
	}
	defer stubDB.Close()

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	router := NewRouter(Deps{Logger: logger, DB: stubDB, JWTSecret: "test", PythonUpstream: upstream.URL})

	req := httptest.NewRequest(http.MethodPost, "/api/v1/studio/projects", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201（应回落 Python，而不是 405）", rec.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("响应不是 JSON: %v", err)
	}
	if body["message"] != "from-python" {
		t.Fatalf("message = %v, want from-python（说明没有真正透传）", body["message"])
	}
}
