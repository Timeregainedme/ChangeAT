package handler

import (
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/middleware"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/response"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/store"
)

// Chapter 提供章节只读接口。
type Chapter struct {
	chapters   *store.ChapterStore
	workspaces *store.WorkspaceStore
}

// NewChapter 构造章节 handler。
func NewChapter(chapters *store.ChapterStore, workspaces *store.WorkspaceStore) *Chapter {
	return &Chapter{chapters: chapters, workspaces: workspaces}
}

// chapterRead 对应 Python 的 `ChapterRead`。
type chapterRead struct {
	ID              string `json:"id"`
	ProjectID       string `json:"project_id"`
	Index           int    `json:"index"`
	Title           string `json:"title"`
	Summary         string `json:"summary"`
	RawText         string `json:"raw_text"`
	CondensedText   string `json:"condensed_text"`
	StoryboardCount int    `json:"storyboard_count"`
	Status          string `json:"status"`
	ShotCount       int    `json:"shot_count"`
}

// List 处理 GET /api/v1/studio/chapters。
func (h *Chapter) List(w http.ResponseWriter, r *http.Request) {
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

	params := store.ChapterListParams{
		WorkspaceID: workspaceID,
		OrderField:  query.Get("order"),
		Desc:        query.Get("is_desc") == "true",
		Page:        page,
		PageSize:    pageSize,
	}
	if v := query.Get("project_id"); v != "" {
		params.ProjectID = &v
	}
	if v := query.Get("q"); v != "" {
		params.Keyword = &v
	}

	items, total, err := h.chapters.List(r.Context(), params)
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取章节列表失败")
		return
	}

	out := make([]chapterRead, 0, len(items))
	for _, item := range items {
		out = append(out, toChapterRead(item))
	}
	response.WriteSuccess(w, newPaginated(out, page, pageSize, total))
}

// Get 处理 GET /api/v1/studio/chapters/{chapter_id}。
func (h *Chapter) Get(w http.ResponseWriter, r *http.Request) {
	workspaceID, ok := h.resolveWorkspace(w, r)
	if !ok {
		return
	}

	item, err := h.chapters.Get(r.Context(), chi.URLParam(r, "chapter_id"), workspaceID)
	if errors.Is(err, store.ErrNotFound) {
		response.WriteError(w, http.StatusNotFound, "Chapter not found")
		return
	}
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取章节失败")
		return
	}
	response.WriteSuccess(w, toChapterRead(item))
}

// resolveWorkspace 解析并校验请求所属工作区。
func (h *Chapter) resolveWorkspace(w http.ResponseWriter, r *http.Request) (string, bool) {
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

// toChapterRead 把 store 结构转成响应结构。
func toChapterRead(c *store.Chapter) chapterRead {
	return chapterRead{
		ID:              c.ID,
		ProjectID:       c.ProjectID,
		Index:           c.Index,
		Title:           c.Title,
		Summary:         c.Summary,
		RawText:         c.RawText,
		CondensedText:   c.CondensedText,
		StoryboardCount: c.StoryboardCount,
		Status:          c.Status,
		ShotCount:       c.ShotCount,
	}
}
