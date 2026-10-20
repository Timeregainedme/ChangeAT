package handler

import "testing"

// TestIsAbsoluteURL 覆盖「什么算可重定向的绝对地址」。
//
// 这是安全边界而非格式判断：如果把 `data:` / `javascript:` 当成跳转目标，
// 一个匿名可访问的下载端点就变成了开放重定向与 XSS 入口。
func TestIsAbsoluteURL(t *testing.T) {
	cases := []struct {
		in   string
		want bool
	}{
		{"https://pub-6dcd.r2.dev/files/a.png", true},
		{"http://127.0.0.1:9000/bucket/a.png", true},
		{"HTTPS://EXAMPLE.COM/a.png", true},      // scheme 大小写不敏感
		{"  https://example.com/a.png  ", false}, // 带空白不直接放行（调用方已 TrimSpace）
		{"files/a.png", false},
		{"", false},
		{"data:image/png;base64,AAAA", false},
		{"javascript:alert(1)", false},
		{"//evil.example.com/a.png", false}, // 协议相对地址不认，避免被当成同站跳转
	}

	for _, tc := range cases {
		if got := isAbsoluteURL(tc.in); got != tc.want {
			t.Errorf("isAbsoluteURL(%q) = %v, want %v", tc.in, got, tc.want)
		}
	}
}

// TestIsAbsoluteURLTrimsBeforeCheck 说明调用方必须先 TrimSpace。
//
// 生产数据里 thumbnail 来自数据库，可能存在首尾空白；
// 不 trim 会导致「明明是绝对 URL 却走了 fallback」，表现为下载变慢而不是报错，
// 很难被发现。
func TestIsAbsoluteURLTrimsBeforeCheck(t *testing.T) {
	raw := "  https://example.com/a.png  "
	trimmed := "https://example.com/a.png"
	if isAbsoluteURL(raw) {
		t.Fatal("未 trim 的字符串不应被判定为绝对 URL")
	}
	if !isAbsoluteURL(trimmed) {
		t.Fatal("trim 后应判定为绝对 URL")
	}
}
