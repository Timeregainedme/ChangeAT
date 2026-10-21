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
	// 风格目录已从枚举升级为表（用户可以在「风格管理」里增删改）。
	// 这里优先读表；读不到（表为空 / 查询失败）时回落到内置列表，
	// 保证新建项目的下拉永远不会空。
	rows, err := h.projects.ListStyleOptions(r.Context())
	if err == nil && len(rows) > 0 {
		grouped := make(map[string][]styleOption)
		order := make([]string, 0, 4)
		for _, row := range rows {
			if _, ok := grouped[row.VisualStyle]; !ok {
				order = append(order, row.VisualStyle)
			}
			grouped[row.VisualStyle] = append(grouped[row.VisualStyle], styleOption{
				Value: row.Name,
				Label: row.Name,
			})
		}

		defaults := make(map[string]string, len(grouped))
		visuals := make([]styleOption, 0, len(order))
		// 现实排在前：与 Python 种子顺序和前端默认选中项保持一致
		for _, visual := range sortVisualStyles(order) {
			visuals = append(visuals, styleOption{Value: visual, Label: visual})
			if len(grouped[visual]) > 0 {
				defaults[visual] = grouped[visual][0].Value
			}
		}

		response.WriteSuccess(w, projectStyleOptions{
			VisualStyles:              visuals,
			StylesByVisualStyle:       grouped,
			DefaultStyleByVisualStyle: defaults,
		})
		return
	}

	// 回退：内置静态目录
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

// sortVisualStyles 把「现实 / 动漫」固定排前，其余按出现顺序追加。
func sortVisualStyles(order []string) []string {
	result := make([]string, 0, len(order))
	seen := map[string]bool{}
	for _, preferred := range []string{visualStyleLiveAction, visualStyleAnime} {
		for _, visual := range order {
			if visual == preferred && !seen[visual] {
				result = append(result, visual)
				seen[visual] = true
			}
		}
	}
	for _, visual := range order {
		if !seen[visual] {
			result = append(result, visual)
			seen[visual] = true
		}
	}
	return result
}
