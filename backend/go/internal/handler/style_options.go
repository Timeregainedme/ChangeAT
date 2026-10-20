package handler

import (
	"net/http"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/response"
)

// styleOption 对应 Python 的 `StyleOption`。
type styleOption struct {
	Value string `json:"value"`
	Label string `json:"label"`
}

// projectStyleOptions 对应 Python 的 `ProjectStyleOptionsRead`。
type projectStyleOptions struct {
	VisualStyles              []styleOption            `json:"visual_styles"`
	StylesByVisualStyle       map[string][]styleOption `json:"styles_by_visual_style"`
	DefaultStyleByVisualStyle map[string]string        `json:"default_style_by_visual_style"`
}

// 与 Python 的 `ProjectStyle` / `ProjectVisualStyle` 枚举逐字一致。
//
// 这些中文值直接存在 `projects.style` / `projects.visual_style` 列里，
// 也是前端下拉框的 value。改动任何一个都会让存量项目变成「未知风格」。
const (
	visualStyleLiveAction = "现实"
	visualStyleAnime      = "动漫"

	styleRealPeopleCity    = "真人都市"
	styleRealPeopleScifi   = "真人科幻"
	styleRealPeopleAncient = "真人古装"
	styleAnimeScifi        = "动漫科幻"
	styleAnime3D           = "动漫3D"
	styleGuoman            = "国漫"
	styleInkWash           = "水墨画"
)

// StyleOptions 处理 GET /api/v1/studio/projects/style-options。
//
// 为什么要在 Go 侧实现这个静态接口：
// 切流用的是正则 `^/api/v1/studio/projects/[^/]+$`，它会把 `style-options`
// 也匹配进来（当成 project_id）。若不实现，前端新建项目时下拉框会 404。
// 与其在 Nginx 里加排除规则（容易被后续新增子路径漏掉），不如把这个纯静态
// 接口一并接管 —— 它没有数据库依赖，出错面为零。
func (h *Project) StyleOptions(w http.ResponseWriter, r *http.Request) {
	// 顺序必须与 Python 枚举声明顺序一致：前端默认选中第一项。
	grouped := map[string][]styleOption{
		visualStyleLiveAction: {
			{Value: styleRealPeopleCity, Label: styleRealPeopleCity},
			{Value: styleRealPeopleScifi, Label: styleRealPeopleScifi},
			{Value: styleRealPeopleAncient, Label: styleRealPeopleAncient},
		},
		visualStyleAnime: {
			{Value: styleAnimeScifi, Label: styleAnimeScifi},
			{Value: styleAnime3D, Label: styleAnime3D},
			{Value: styleGuoman, Label: styleGuoman},
			{Value: styleInkWash, Label: styleInkWash},
		},
	}

	defaults := make(map[string]string, len(grouped))
	for visual, styles := range grouped {
		if len(styles) > 0 {
			defaults[visual] = styles[0].Value
		}
	}

	response.WriteSuccess(w, projectStyleOptions{
		VisualStyles: []styleOption{
			{Value: visualStyleLiveAction, Label: visualStyleLiveAction},
			{Value: visualStyleAnime, Label: visualStyleAnime},
		},
		StylesByVisualStyle:       grouped,
		DefaultStyleByVisualStyle: defaults,
	})
}
