// Package proxy 提供到 Python 上游的透传。
//
// 用途有两个：
//  1. 某个接口在 Go 侧只实现了「主路径」，边界分支（如私有桶下的流式下载）
//     仍然交给 Python —— 返回 502 会让这部分功能直接不可用；
//  2. 后续「厚业务反代」的基础设施（studio/* 长期留在 Python）。
//
// 为什么用 httputil.ReverseProxy 而不是自己 http.Client 转发：
// ReverseProxy 已经处理好流式响应、`Range` 透传、`Connection` 等逐跳头、
// 以及客户端断开时的取消传播。自己写很容易在这些细节上出错，
// 而它们恰好是文件下载/视频播放最依赖的部分。
package proxy

import (
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"
)

// ToPython 构造一个指向 Python API 的反向代理。
//
// 上游地址解析失败时返回 nil，调用方应据此决定「不注册该路由」而不是 panic ——
// 一个配置错误不应该让整个进程起不来。
func ToPython(upstream string) *httputil.ReverseProxy {
	target, err := url.Parse(upstream)
	if err != nil || target.Scheme == "" || target.Host == "" {
		return nil
	}

	rp := httputil.NewSingleHostReverseProxy(target)

	// 保留原始 Host：Python 侧的 CORS 与部分重定向逻辑依赖它。
	originalDirector := rp.Director
	rp.Director = func(r *http.Request) {
		originalDirector(r)
		r.Host = target.Host
	}

	// 长响应（视频）不能因为 30s 空闲被切断；与 Nginx 侧的 300s 对齐。
	rp.Transport = &http.Transport{
		Proxy:                 http.ProxyFromEnvironment,
		MaxIdleConns:          32,
		MaxIdleConnsPerHost:   16,
		IdleConnTimeout:       90 * time.Second,
		ResponseHeaderTimeout: 60 * time.Second,
		DisableCompression:    true, // 二进制流不做透明压缩，避免 Content-Length 失真
	}

	// 上游不可达时返回与其余接口一致的 503 信封，而不是裸文本。
	rp.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = w.Write([]byte(`{"code":503,"message":"upstream unavailable","data":null,"meta":null}`))
	}

	return rp
}
