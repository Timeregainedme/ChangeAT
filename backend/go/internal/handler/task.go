package handler

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/middleware"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/response"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/store"
)

// Task 提供任务状态与结果查询。
//
// 这两个接口是前端任务中心的高频轮询入口，也是这次迁移价值最高的一条：
// 单表、只读、量大。语义必须与 Python 的 `SqlAlchemyTaskStore` 完全一致，
// 否则前端会看到「进度倒退」「耗时突然归零」这类难以归因的异常。
type Task struct {
	tasks      *store.TaskStore
	workspaces *store.WorkspaceStore
}

// NewTask 构造任务 handler。
func NewTask(tasks *store.TaskStore, workspaces *store.WorkspaceStore) *Task {
	return &Task{tasks: tasks, workspaces: workspaces}
}

// taskStatusRead 对应 Python 的 `TaskStatusRead`。
type taskStatusRead struct {
	TaskID            string   `json:"task_id"`
	Status            string   `json:"status"`
	Progress          int      `json:"progress"`
	CancelRequested   bool     `json:"cancel_requested"`
	CancelRequestedAt *float64 `json:"cancel_requested_at_ts"`
	StartedAt         *float64 `json:"started_at_ts"`
	FinishedAt        *float64 `json:"finished_at_ts"`
	ElapsedMS         *int64   `json:"elapsed_ms"`
}

// taskResultRead 对应 Python 的 `TaskResultRead`。
type taskResultRead struct {
	TaskID            string   `json:"task_id"`
	Status            string   `json:"status"`
	Progress          int      `json:"progress"`
	Result            any      `json:"result"`
	Error             string   `json:"error"`
	CancelRequested   bool     `json:"cancel_requested"`
	CancelRequestedAt *float64 `json:"cancel_requested_at_ts"`
	StartedAt         *float64 `json:"started_at_ts"`
	FinishedAt        *float64 `json:"finished_at_ts"`
	ElapsedMS         *int64   `json:"elapsed_ms"`
}

// taskListItemRead 对应 Python 的 `TaskListItemRead`。
type taskListItemRead struct {
	TaskID                   string   `json:"task_id"`
	TaskKind                 string   `json:"task_kind"`
	Status                   string   `json:"status"`
	Progress                 int      `json:"progress"`
	CancelRequested          bool     `json:"cancel_requested"`
	CancelRequestedAt        *float64 `json:"cancel_requested_at_ts"`
	StartedAt                *float64 `json:"started_at_ts"`
	FinishedAt               *float64 `json:"finished_at_ts"`
	ElapsedMS                *int64   `json:"elapsed_ms"`
	CreatedAt                *float64 `json:"created_at_ts"`
	UpdatedAt                *float64 `json:"updated_at_ts"`
	ExecutorType             string   `json:"executor_type"`
	ExecutorTaskID           *string  `json:"executor_task_id"`
	RelationType             *string  `json:"relation_type"`
	RelationEntityID         *string  `json:"relation_entity_id"`
	ResourceType             *string  `json:"resource_type"`
	NavigateRelationType     *string  `json:"navigate_relation_type"`
	NavigateRelationEntityID *string  `json:"navigate_relation_entity_id"`
}

// List 处理 GET /api/v1/film/tasks（任务中心全局列表）。
//
// 参数细节必须与 Python 一致：
//   - `statuses` 可多值（`?statuses=succeeded&statuses=failed`）；
//   - `recent_seconds` 默认 300，范围 0~86400，且**仅在未指定 statuses 时生效**
//     （Python 用的是 elif 分支）；
//   - `page_size` 默认 20，范围 1~100。
func (h *Task) List(w http.ResponseWriter, r *http.Request) {
	workspaceID, ok := h.resolveWorkspace(w, r)
	if !ok {
		return
	}

	query := r.URL.Query()
	page, pageSize, msg := parsePaginationWithDefault(query.Get("page"), query.Get("page_size"), 20)
	if msg != "" {
		response.WriteError(w, http.StatusUnprocessableEntity, msg)
		return
	}

	recentSeconds := 300
	if raw := query.Get("recent_seconds"); raw != "" {
		v, err := strconv.Atoi(raw)
		if err != nil {
			response.WriteError(w, http.StatusUnprocessableEntity,
				"query.recent_seconds: Input should be a valid integer, unable to parse string as an integer")
			return
		}
		if v < 0 || v > 86400 {
			response.WriteError(w, http.StatusUnprocessableEntity,
				"query.recent_seconds: Input should be between 0 and 86400")
			return
		}
		recentSeconds = v
	}

	params := store.TaskListParams{
		WorkspaceID:   workspaceID,
		Statuses:      query["statuses"],
		RecentSeconds: recentSeconds,
		Page:          page,
		PageSize:      pageSize,
	}
	if v := query.Get("task_kind"); v != "" {
		params.TaskKind = &v
	}
	if v := query.Get("relation_type"); v != "" {
		params.RelationType = &v
	}
	if v := query.Get("relation_entity_id"); v != "" {
		params.RelationEntityID = &v
	}

	items, total, err := h.tasks.ListTaskViews(r.Context(), params)
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取任务列表失败")
		return
	}

	out := make([]taskListItemRead, 0, len(items))
	for _, item := range items {
		out = append(out, taskListItemRead{
			TaskID:                   item.ID,
			TaskKind:                 item.TaskKind,
			Status:                   item.Status,
			Progress:                 item.Progress,
			CancelRequested:          item.CancelRequested,
			CancelRequestedAt:        unixSeconds(item.CancelRequestedAt),
			StartedAt:                unixSeconds(item.StartedAt),
			FinishedAt:               unixSeconds(item.FinishedAt),
			ElapsedMS:                item.ElapsedMS,
			CreatedAt:                unixSeconds(item.CreatedAt),
			UpdatedAt:                unixSeconds(item.UpdatedAt),
			ExecutorType:             item.ExecutorType,
			ExecutorTaskID:           item.ExecutorTaskID,
			RelationType:             item.RelationType,
			RelationEntityID:         item.RelationEntityID,
			ResourceType:             item.ResourceType,
			NavigateRelationType:     item.NavigateRelationType,
			NavigateRelationEntityID: item.NavigateRelationEntityID,
		})
	}
	response.WriteSuccess(w, newPaginated(out, page, pageSize, total))
}

// taskLinkRead 对应 Python 的 `GenerationTaskLinkRead`。
type taskLinkRead struct {
	ID               int     `json:"id"`
	TaskID           string  `json:"task_id"`
	ResourceType     string  `json:"resource_type"`
	RelationType     string  `json:"relation_type"`
	RelationEntityID string  `json:"relation_entity_id"`
	FileID           *string `json:"file_id"`
	Status           string  `json:"status"`
}

// ListLinks 处理 GET /api/v1/film/task-links。
func (h *Task) ListLinks(w http.ResponseWriter, r *http.Request) {
	workspaceID, ok := h.resolveWorkspace(w, r)
	if !ok {
		return
	}

	query := r.URL.Query()
	page, pageSize, msg := parsePaginationWithDefault(query.Get("page"), query.Get("page_size"), 10)
	if msg != "" {
		response.WriteError(w, http.StatusUnprocessableEntity, msg)
		return
	}

	params := store.TaskLinkListParams{
		WorkspaceID: workspaceID,
		OrderField:  query.Get("order"),
		// Python 侧 is_desc 默认 true（任务关联默认按最近更新倒序）
		Desc:     query.Get("is_desc") != "false",
		Page:     page,
		PageSize: pageSize,
	}
	for _, f := range []struct {
		dest   **string
		source string
	}{
		{&params.ResourceType, "resource_type"},
		{&params.RelationType, "relation_type"},
		{&params.RelationEntityID, "relation_entity_id"},
		{&params.Status, "status"},
		{&params.TaskID, "task_id"},
	} {
		if v := query.Get(f.source); v != "" {
			value := v
			*f.dest = &value
		}
	}

	items, total, err := h.tasks.ListTaskLinks(r.Context(), params)
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取任务关联失败")
		return
	}

	out := make([]taskLinkRead, 0, len(items))
	for _, item := range items {
		out = append(out, taskLinkRead{
			ID:               item.ID,
			TaskID:           item.TaskID,
			ResourceType:     item.ResourceType,
			RelationType:     item.RelationType,
			RelationEntityID: item.RelationEntityID,
			FileID:           item.FileID,
			Status:           item.Status,
		})
	}
	response.WriteSuccess(w, newPaginated(out, page, pageSize, total))
}

// Status 处理 GET /api/v1/film/tasks/{task_id}/status。
//
// 用 GetStatus（不取 result/error）：状态轮询是高频调用，
// 而 result 可能有几十 KB，多读这一列会让轮询成本成倍上升。
func (h *Task) Status(w http.ResponseWriter, r *http.Request) {
	task, ok := h.loadScoped(w, r, h.tasks.GetStatus)
	if !ok {
		return
	}

	response.WriteSuccess(w, taskStatusRead{
		TaskID:            task.ID,
		Status:            task.Status,
		Progress:          task.Progress,
		CancelRequested:   task.CancelRequested,
		CancelRequestedAt: unixSeconds(task.CancelRequestedAt),
		StartedAt:         unixSeconds(task.StartedAt),
		FinishedAt:        unixSeconds(task.FinishedAt),
		ElapsedMS:         elapsedMillis(task.StartedAt, task.FinishedAt),
	})
}

// Result 处理 GET /api/v1/film/tasks/{task_id}/result。
func (h *Task) Result(w http.ResponseWriter, r *http.Request) {
	task, ok := h.loadScoped(w, r, h.tasks.GetResult)
	if !ok {
		return
	}

	var result any
	if len(task.Result) > 0 {
		result = task.Result
	}

	response.WriteSuccess(w, taskResultRead{
		TaskID:            task.ID,
		Status:            task.Status,
		Progress:          task.Progress,
		Result:            result,
		Error:             task.Error,
		CancelRequested:   task.CancelRequested,
		CancelRequestedAt: unixSeconds(task.CancelRequestedAt),
		StartedAt:         unixSeconds(task.StartedAt),
		FinishedAt:        unixSeconds(task.FinishedAt),
		ElapsedMS:         elapsedMillis(task.StartedAt, task.FinishedAt),
	})
}

// loadScoped 读取任务并校验工作区归属。
//
// 归属不通过时**统一回 404 而不是 403**：403 等于告诉调用方
// 「这个 task_id 是真的，只是你没权限」，把别家的任务 ID 变成可枚举面。
// 与 Python 的 scoping 约定一致。
func (h *Task) loadScoped(
	w http.ResponseWriter,
	r *http.Request,
	fetch func(ctx context.Context, id string) (*store.GenerationTask, error),
) (*store.GenerationTask, bool) {
	taskID := chi.URLParam(r, "task_id")
	if taskID == "" {
		response.WriteError(w, http.StatusNotFound, "Task not found")
		return nil, false
	}

	userID, ok := middleware.UserIDFromContext(r.Context())
	if !ok {
		response.WriteError(w, http.StatusUnauthorized, "未登录，请先登录")
		return nil, false
	}

	workspaceID, _, err := h.workspaces.Resolve(r.Context(), userID, r.Header.Get("X-Workspace-ID"))
	if errors.Is(err, store.ErrNotFound) {
		// 与 Python 一致：工作区解析失败时也回 404「工作区不存在」。
		response.WriteError(w, http.StatusNotFound, "工作区不存在")
		return nil, false
	}
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取工作区失败")
		return nil, false
	}

	task, err := fetch(r.Context(), taskID)
	if errors.Is(err, store.ErrNotFound) {
		response.WriteError(w, http.StatusNotFound, "Task not found")
		return nil, false
	}
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取任务失败")
		return nil, false
	}
	if task.WorkspaceID != workspaceID {
		response.WriteError(w, http.StatusNotFound, "Task not found")
		return nil, false
	}

	return task, true
}

// resolveWorkspace 解析当前请求所属工作区。
func (h *Task) resolveWorkspace(w http.ResponseWriter, r *http.Request) (string, bool) {
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

// unixSeconds 把时间转成 UNIX 秒（float）。
//
// 必须与 Python 的 `datetime.timestamp()` 等价：
// 服务器 TZ=UTC 且 MySQL DATETIME 无时区，Python 对 naive datetime 调 timestamp()
// 会按本地时区（UTC）解释，因此这里用 UTC 直接取 Unix 秒即可。
// 若将来服务器改成非 UTC 时区，两侧需要一起调整 —— 这个依赖已写进架构文档。
func unixSeconds(t *time.Time) *float64 {
	if t == nil {
		return nil
	}
	v := float64(t.Unix())
	return &v
}

// elapsedMillis 计算累计执行耗时。
//
// 与 Python 的 `_elapsed_ms_from_datetimes` 一致：
//   - 未开始 → nil（不是 0）；
//   - 已结束 → finished - started；
//   - 进行中 → now - started（用 UTC 与 naive 相减同样的语义）。
func elapsedMillis(startedAt, finishedAt *time.Time) *int64 {
	if startedAt == nil {
		return nil
	}
	end := time.Now().UTC()
	if finishedAt != nil {
		end = *finishedAt
	}
	ms := end.Sub(*startedAt).Milliseconds()
	if ms < 0 {
		ms = 0
	}
	return &ms
}
