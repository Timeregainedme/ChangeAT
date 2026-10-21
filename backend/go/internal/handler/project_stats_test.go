package handler

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/store"
)

// TestMergeStats 覆盖统计合并的三条关键约定：
// 实时值覆盖存量、存量其余键保留、时间戳转 UTC RFC3339。
func TestMergeStats(t *testing.T) {
	updatedAt := time.Date(2026, 10, 21, 8, 30, 0, 0, time.UTC)
	computed := &store.ProjectStats{Chapters: 2, Roles: 5, Scenes: 8, Props: 3}

	t.Run("覆盖同名键并保留其它键", func(t *testing.T) {
		raw := json.RawMessage(`{"chapters":0,"legacy_note":"keep-me"}`)
		merged := mergeStats(raw, computed, updatedAt)

		var out map[string]any
		if err := json.Unmarshal(merged, &out); err != nil {
			t.Fatalf("结果不是合法 JSON: %v", err)
		}
		if out["chapters"] != float64(2) {
			t.Fatalf("chapters 应被实时值覆盖，实际 %v", out["chapters"])
		}
		if out["legacy_note"] != "keep-me" {
			t.Fatalf("存量键应保留，实际 %v", out["legacy_note"])
		}
		if out["updated_at"] != "2026-10-21T08:30:00Z" {
			t.Fatalf("updated_at 格式不对：%v", out["updated_at"])
		}
	})

	t.Run("统计查询失败时不清空存量值", func(t *testing.T) {
		raw := json.RawMessage(`{"chapters":7}`)
		merged := mergeStats(raw, nil, time.Time{})

		var out map[string]any
		if err := json.Unmarshal(merged, &out); err != nil {
			t.Fatalf("结果不是合法 JSON: %v", err)
		}
		if out["chapters"] != float64(7) {
			t.Fatalf("降级时应保留存量 chapters，实际 %v", out["chapters"])
		}
		if _, ok := out["updated_at"]; ok {
			t.Fatal("时间为零值时不应写入 updated_at")
		}
	})

	t.Run("存量 JSON 非法时返回聚合结果", func(t *testing.T) {
		merged := mergeStats(json.RawMessage(`not-json`), computed, time.Time{})

		var out map[string]any
		if err := json.Unmarshal(merged, &out); err != nil {
			t.Fatalf("结果不是合法 JSON: %v", err)
		}
		if out["roles"] != float64(5) {
			t.Fatalf("非法存量不应影响聚合值，实际 %v", out["roles"])
		}
	})
}
