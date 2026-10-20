package handler

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/middleware"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/response"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/store"
)

// Project 提供项目只读接口。
//
// 本阶段刻意只做 GET：写操作一旦出错是「写坏数据」，与读的失败模式完全不同。
// 只读接口先切流观察一段时间，再考虑接管 POST/PATCH/DELETE。
type Project struct {
	projects   *store.ProjectStore
	workspaces *store.WorkspaceStore
}

// NewProject 构造项目 handler。
func NewProject(projects *store.ProjectStore, workspaces *store.WorkspaceStore) *Project {
	return &Project{projects: projects, workspaces: workspaces}
}

// projectRead 对应 Python 的 `ProjectRead`。
type projectRead struct {
	ID                            string          `json:"id"`
	Name                          string          `json:"name"`
	Description                   string          `json:"description"`
	Style                         string          `json:"style"`
	VisualStyle                   string          `json:"visual_style"`
	Seed                          int             `json:"seed"`
	UnifyStyle                    bool            `json:"unify_style"`
	Progress                      int             `json:"progress"`
	DefaultVideoRatio             *string         `json:"default_video_ratio"`
	DefaultImageRatio             *string         `json:"default_image_ratio"`
	DefaultImageResolutionProfile *string         `json:"default_image_resolution_profile"`
	UseDialogAudioAsReference     bool            `json:"use_dialog_audio_as_reference"`
	Stats                         json.RawMessage `json:"stats"`
	WorkspaceID                   string          `json:"workspace_id"`
	CreatedBy                     *int            `json:"created_by"`
}

// pagination 对应 Python 的 `Pagination`。
type pagination struct {
	Page     int `json:"page"`
	PageSize int `json:"page_size"`
	Total    int `json:"total"`
	MaxPage  int `json:"max_page"`
}

// paginated 对应 Python 的 `PaginatedData`。
type paginated struct {
	Items      any        `json:"items"`
	Pagination pagination `json:"pagination"`
}

// newPaginated 计算 max_page 并组装分页体。
//
// max_page 的算法必须与 Python 一致：`max(1, ceil(total/page_size))`。
// 空结果时是 1 而不是 0 —— 前端用 max_page 控制页码组件的上限，
// 返回 0 会渲染出「第 0 页」这种非法状态。
func newPaginated(items any, page, pageSize, total int) paginated {
	maxPage := 1
	if pageSize > 0 {
		maxPage = (total + pageSize - 1) / pageSize
		if maxPage < 1 {
			maxPage = 1
		}
	}
	return paginated{
		Items: items,
		Pagination: pagination{
			Page:     page,
			PageSize: pageSize,
			Total:    total,
			MaxPage:  maxPage,
		},
	}
}

// List 处理 GET /api/v1/studio/projects。
func (h *Project) List(w http.ResponseWriter, r *http.Request) {
	workspaceID, ok := h.resolveWorkspace(w, r)
	if !ok {
		return
	}

	query := r.URL.Query()
	page, pageSize, msg := parsePagination(query.Get("page"), query.Get("page_size"))
	if msg != "" {
		response.WriteError(w, http.StatusUnprocessableEntity, msg)
		return
	}

	params := store.ProjectListParams{
		WorkspaceID: workspaceID,
		OrderField:  query.Get("order"),
		Desc:        query.Get("is_desc") == "true",
		Page:        page,
		PageSize:    pageSize,
	}
	if q := query.Get("q"); q != "" {
		params.Keyword = &q
	}

	items, total, err := h.projects.List(r.Context(), params)
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取项目列表失败")
		return
	}

	out := make([]projectRead, 0, len(items))
	for _, item := range items {
		out = append(out, toProjectRead(item))
	}
	response.WriteSuccess(w, newPaginated(out, page, pageSize, total))
}

// Get 处理 GET /api/v1/studio/projects/{project_id}。
func (h *Project) Get(w http.ResponseWriter, r *http.Request) {
	workspaceID, ok := h.resolveWorkspace(w, r)
	if !ok {
		return
	}

	item, err := h.projects.Get(r.Context(), chi.URLParam(r, "project_id"), workspaceID)
	if errors.Is(err, store.ErrNotFound) {
		response.WriteError(w, http.StatusNotFound, "Project not found")
		return
	}
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取项目失败")
		return
	}
	response.WriteSuccess(w, toProjectRead(item))
}

// resolveWorkspace 解析并校验请求所属工作区。
func (h *Project) resolveWorkspace(w http.ResponseWriter, r *http.Request) (string, bool) {
	userID, ok := middleware.UserIDFromContext(r.Context())
	if !ok {
		response.WriteError(w, http.StatusUnauthorized, "未登录，请先登录")
		return "", false
	}
	workspaceID, _, err := h.workspaces.Resolve(r.Context(), userID, r.Header.Get("X-Workspace-ID"))
	if errors.Is(err, store.ErrNotFound) {
		response.WriteError(w, http.StatusNotFound, "工作区不存在")
		return "", false
	}
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取工作区失败")
		return "", false
	}
	return workspaceID, true
}

// toProjectRead 把 store 结构转成响应结构。
func toProjectRead(p *store.Project) projectRead {
	stats := p.Stats
	if len(stats) == 0 {
		stats = json.RawMessage("{}")
	}
	return projectRead{
		ID:                            p.ID,
		Name:                          p.Name,
		Description:                   p.Description,
		Style:                         p.Style,
		VisualStyle:                   p.VisualStyle,
		Seed:                          p.Seed,
		UnifyStyle:                    p.UnifyStyle,
		Progress:                      p.Progress,
		DefaultVideoRatio:             p.DefaultVideoRatio,
		DefaultImageRatio:             p.DefaultImageRatio,
		DefaultImageResolutionProfile: p.DefaultImageResolutionProfile,
		UseDialogAudioAsReference:     p.UseDialogAudioAsReference,
		Stats:                         stats,
		WorkspaceID:                   p.WorkspaceID,
		CreatedBy:                     p.CreatedBy,
	}
}
