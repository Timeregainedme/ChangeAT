package handler

import (
	"errors"
	"net/http"
	"net/http/httputil"
	"strings"

	"github.com/go-chi/chi/v5"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/response"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/store"
)

// File 提供素材下载。
//
// 这个端点**必须匿名可访问**：浏览器 `<img src>` / `<video src>` 无法携带
// Authorization 头，要求登录会让所有素材在前端裂图。安全性由
// 「file_id 是不可枚举的 UUID + 对象存储已配公开读」保证，与 Python 侧一致。
type File struct {
	files *store.FileStore
	// fallback 在无法直接 302 时把请求透传给 Python。
	// 为 nil 表示上游未配置，此时返回 502 并在日志中说明原因。
	fallback *httputil.ReverseProxy
}

// NewFile 构造文件下载 handler。
func NewFile(files *store.FileStore, fallback *httputil.ReverseProxy) *File {
	return &File{files: files, fallback: fallback}
}

// Download 处理 GET / HEAD /api/v1/studio/files/{file_id}/download。
//
// 行为与 Python 的 build_download_response 对齐：
//   - `thumbnail` 是绝对 URL → 302 到对象存储（Range 由对象存储处理，播放器可 seek）；
//   - 否则 → 透传 Python 走流式代理（私有桶 / 未配公开域名的场景）。
//
// 为什么不自己实现流式代理：
// 生产 21 个文件的 thumbnail 全部是 R2 公开 URL，302 覆盖 100% 实际流量；
// 而流式代理要正确处理 Range / 206 / 416 / Content-Range，写错会让 <video> 无法拖动进度。
// 透传给已经验证过的 Python 实现，比在这里重写一遍更安全。
func (h *File) Download(w http.ResponseWriter, r *http.Request) {
	fileID := chi.URLParam(r, "file_id")
	if fileID == "" {
		response.WriteError(w, http.StatusNotFound, "File not found")
		return
	}

	item, err := h.files.GetDownloadMeta(r.Context(), fileID)
	if errors.Is(err, store.ErrNotFound) {
		response.WriteError(w, http.StatusNotFound, "File not found")
		return
	}
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取文件信息失败")
		return
	}

	publicURL := strings.TrimSpace(item.Thumbnail)
	if isAbsoluteURL(publicURL) {
		// 直接写 Location + 302，不用 http.Redirect：
		// 后者会给 GET 请求补一段 HTML 提示体（Content-Length=144），
		// 而 Python 的 RedirectResponse 是空体（Content-Length=0）。
		// 影子里这是唯一的头差异，浏览器虽然会忽略 302 的 body，
		// 但契约对比会一直报不一致 —— 让两边逐字节相同，后续切流才不用逐个解释差异。
		w.Header().Set("Location", publicURL)
		w.WriteHeader(http.StatusFound)
		return
	}

	if h.fallback == nil {
		// 走到这里说明对象存储没配公开域名，而 Go 侧未实现流式代理。
		// 返回 502 而不是 200 空体：让问题在监控上可见，而不是让用户看到「加载失败但没报错」。
		response.WriteError(w, http.StatusBadGateway, "文件代理未启用")
		return
	}
	h.fallback.ServeHTTP(w, r)
}

// isAbsoluteURL 判断字符串是否是可重定向的绝对 URL。
//
// 只认 http/https：`data:` 或 `javascript:` 之类的 scheme 若被当成跳转目标，
// 会把一个下载端点变成开放重定向/XSS 入口。
func isAbsoluteURL(raw string) bool {
	lower := strings.ToLower(raw)
	return strings.HasPrefix(lower, "http://") || strings.HasPrefix(lower, "https://")
}
