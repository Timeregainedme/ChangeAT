package store

import (
	"context"
	"database/sql"
	"fmt"
	"strconv"
	"strings"
	"time"
)

// TaskListParams 是任务列表的查询参数。
//
// 字段与 Python 的 `list_tasks` 路由参数一一对应；nil 表示未提供。
type TaskListParams struct {
	WorkspaceID      string
	Statuses         []string
	TaskKind         *string
	RelationType     *string
	RelationEntityID *string
	// RecentSeconds 只在 Statuses 为空时生效（与 Python 的 elif 分支一致）。
	RecentSeconds int
	Page          int
	PageSize      int
}

// TaskListItem 是列表项，对应 Python 的 `TaskListItemView`。
type TaskListItem struct {
	ID                       string
	TaskKind                 string
	Status                   string
	Progress                 int
	CancelRequested          bool
	CancelRequestedAt        *time.Time
	StartedAt                *time.Time
	FinishedAt               *time.Time
	ElapsedMS                *int64
	CreatedAt                *time.Time
	UpdatedAt                *time.Time
	ExecutorType             string
	ExecutorTaskID           *string
	RelationType             *string
	RelationEntityID         *string
	ResourceType             *string
	NavigateRelationType     *string
	NavigateRelationEntityID *string
}

// 导航目标映射：relation_type → (navigate_relation_type) 。
//
// 与 Python 的 `_resolve_navigation_targets` 逐项一致。前端用这两个字段决定
// 「点击任务跳到哪个页面」，映射错了会让用户跳到不相关的镜头/章节。
var (
	navigateChapterRelationTypes = map[string]string{
		"chapter_division":      "chapter",
		"script_extraction":     "chapter",
		"consistency_check":     "chapter",
		"script_optimization":   "chapter",
		"script_simplification": "chapter",
	}
	navigateShotRelationTypes = map[string]string{
		"video":                   "shot",
		"shot_first_frame_prompt": "shot",
		"shot_last_frame_prompt":  "shot",
		"shot_key_frame_prompt":   "shot",
	}
	// image 类关系需要再查一次图片表，拿到「图片属于哪个资产」。
	// 表名与列名与 Python 的映射保持一致。
	navigateImageRelations = map[string]struct {
		table     string
		ownerCol  string
		navigateT string
	}{
		"actor_image":     {"actor_images", "actor_id", "actor"},
		"scene_image":     {"scene_images", "scene_id", "scene"},
		"prop_image":      {"prop_images", "prop_id", "prop"},
		"costume_image":   {"costume_images", "costume_id", "costume"},
		"character_image": {"character_images", "character_id", "character"},
	}
)

// ListTaskViews 分页查询任务列表。
func (s *TaskStore) ListTaskViews(ctx context.Context, params TaskListParams) ([]*TaskListItem, int, error) {
	joinLinks := params.RelationType != nil || params.RelationEntityID != nil

	filters := []string{"workspace_id = ?"}
	args := []any{params.WorkspaceID}

	if params.RelationType != nil {
		filters = append(filters, "l.relation_type = ?")
		args = append(args, *params.RelationType)
	}
	if params.RelationEntityID != nil {
		filters = append(filters, "l.relation_entity_id = ?")
		args = append(args, *params.RelationEntityID)
	}

	if len(params.Statuses) > 0 {
		placeholders := make([]string, len(params.Statuses))
		for i, st := range params.Statuses {
			placeholders[i] = "?"
			args = append(args, st)
		}
		filters = append(filters, "status IN ("+strings.Join(placeholders, ",")+")")
	} else if params.RecentSeconds >= 0 {
		// 与 Python 一致：活跃任务无条件保留，终态任务只在时间窗内。
		// 时间窗用 UTC 计算 —— 服务器 TZ=UTC，与 Python 的
		// datetime.now(UTC).replace(tzinfo=None) 等价。
		cutoff := time.Now().UTC().Add(-time.Duration(params.RecentSeconds) * time.Second).
			Format("2006-01-02 15:04:05")
		filters = append(filters, "(status IN ('pending','running','streaming') OR updated_at >= ?)")
		args = append(args, cutoff)
	}

	if params.TaskKind != nil {
		filters = append(filters, "task_kind = ?")
		args = append(args, *params.TaskKind)
	}

	from := "generation_tasks t"
	if joinLinks {
		from += " JOIN generation_task_links l ON l.task_id = t.id"
	}
	whereSQL := " WHERE " + strings.Join(prefixColumns(filters, "t."), " AND ")

	countExpr := "COUNT(*)"
	if joinLinks {
		// 一个任务可能有多条 link，join 后必须去重，否则 total 会虚高。
		countExpr = "COUNT(DISTINCT t.id)"
	}
	var total int
	if err := s.db.QueryRowContext(ctx, "SELECT "+countExpr+" FROM "+from+whereSQL, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	idSQL := "SELECT t.id FROM " + from + whereSQL
	if joinLinks {
		idSQL += " GROUP BY t.id, t.updated_at"
	}
	idSQL += " ORDER BY t.updated_at DESC, t.id DESC LIMIT ? OFFSET ?"
	idArgs := append(append([]any{}, args...), params.PageSize, (params.Page-1)*params.PageSize)

	rows, err := s.db.QueryContext(ctx, idSQL, idArgs...)
	if err != nil {
		return nil, 0, err
	}
	orderedIDs := make([]string, 0, params.PageSize)
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, 0, err
		}
		orderedIDs = append(orderedIDs, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, 0, err
	}
	if len(orderedIDs) == 0 {
		return []*TaskListItem{}, total, nil
	}

	tasks, err := s.loadTasksByIDs(ctx, orderedIDs)
	if err != nil {
		return nil, 0, err
	}

	links, err := s.loadFirstLinks(ctx, orderedIDs)
	if err != nil {
		return nil, 0, err
	}

	nav, err := s.resolveNavigation(ctx, links)
	if err != nil {
		return nil, 0, err
	}

	items := make([]*TaskListItem, 0, len(orderedIDs))
	for _, id := range orderedIDs {
		task, ok := tasks[id]
		if !ok {
			continue
		}
		item := &TaskListItem{
			ID:                task.ID,
			TaskKind:          task.TaskKind,
			Status:            task.Status,
			Progress:          task.Progress,
			CancelRequested:   task.CancelRequested,
			CancelRequestedAt: task.CancelRequestedAt,
			StartedAt:         task.StartedAt,
			FinishedAt:        task.FinishedAt,
			ElapsedMS:         elapsedMillisOf(task.StartedAt, task.FinishedAt),
			CreatedAt:         task.CreatedAt,
			UpdatedAt:         task.UpdatedAt,
			ExecutorType:      task.ExecutorType,
			ExecutorTaskID:    task.ExecutorTaskID,
		}
		if link, ok := links[id]; ok {
			item.RelationType = link.RelationType
			item.RelationEntityID = link.RelationEntityID
			item.ResourceType = link.ResourceType
		}
		if target, ok := nav[id]; ok {
			item.NavigateRelationType = &target[0]
			item.NavigateRelationEntityID = &target[1]
		}
		items = append(items, item)
	}
	return items, total, nil
}

// prefixColumns 给过滤条件补上表别名，避免 join 后列名歧义。
func prefixColumns(filters []string, prefix string) []string {
	out := make([]string, len(filters))
	for i, f := range filters {
		switch {
		case strings.HasPrefix(f, "("), strings.Contains(f, "t."), strings.Contains(f, "l."):
			out[i] = f
		default:
			out[i] = prefix + f
		}
	}
	return out
}

// taskRow 是列表需要的任务列。
type taskRow struct {
	ID                string
	TaskKind          string
	Status            string
	Progress          int
	CancelRequested   bool
	CancelRequestedAt *time.Time
	StartedAt         *time.Time
	FinishedAt        *time.Time
	CreatedAt         *time.Time
	UpdatedAt         *time.Time
	ExecutorType      string
	ExecutorTaskID    *string
}

// loadTasksByIDs 批量取任务行。
func (s *TaskStore) loadTasksByIDs(ctx context.Context, ids []string) (map[string]*taskRow, error) {
	placeholders := make([]string, len(ids))
	args := make([]any, len(ids))
	for i, id := range ids {
		placeholders[i] = "?"
		args[i] = id
	}

	query := `
		SELECT id, task_kind, status, progress, cancel_requested, cancel_requested_at,
		       started_at, finished_at, created_at, updated_at, executor_type, executor_task_id
		FROM generation_tasks
		WHERE id IN (` + strings.Join(placeholders, ",") + `)`

	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make(map[string]*taskRow, len(ids))
	for rows.Next() {
		var t taskRow
		var executorTaskID sql.NullString
		if err := rows.Scan(
			&t.ID, &t.TaskKind, &t.Status, &t.Progress, &t.CancelRequested, &t.CancelRequestedAt,
			&t.StartedAt, &t.FinishedAt, &t.CreatedAt, &t.UpdatedAt, &t.ExecutorType, &executorTaskID,
		); err != nil {
			return nil, err
		}
		if executorTaskID.Valid {
			t.ExecutorTaskID = &executorTaskID.String
		}
		out[t.ID] = &t
	}
	return out, rows.Err()
}

// taskLinkRow 是列表需要的关联列。
type taskLinkRow struct {
	TaskID           string
	ResourceType     *string
	RelationType     *string
	RelationEntityID *string
}

// loadFirstLinks 每个任务取最新一条关联。
//
// 与 Python 一致：按 updated_at DESC, id DESC 排序后取首条。
// 一个任务可能关联多个资源，但列表只展示「主关联」用于跳转。
func (s *TaskStore) loadFirstLinks(ctx context.Context, taskIDs []string) (map[string]*taskLinkRow, error) {
	placeholders := make([]string, len(taskIDs))
	args := make([]any, len(taskIDs))
	for i, id := range taskIDs {
		placeholders[i] = "?"
		args[i] = id
	}

	query := `
		SELECT task_id, resource_type, relation_type, relation_entity_id
		FROM generation_task_links
		WHERE task_id IN (` + strings.Join(placeholders, ",") + `)
		ORDER BY updated_at DESC, id DESC`

	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make(map[string]*taskLinkRow, len(taskIDs))
	for rows.Next() {
		var l taskLinkRow
		if err := rows.Scan(&l.TaskID, &l.ResourceType, &l.RelationType, &l.RelationEntityID); err != nil {
			return nil, err
		}
		if _, exists := out[l.TaskID]; exists {
			continue // 只保留首条
		}
		out[l.TaskID] = &l
	}
	return out, rows.Err()
}

// resolveNavigation 解析任务的跳转目标。
//
// 三类规则（与 Python 的 `_resolve_navigation_targets` 一致）：
//  1. 章节类 → 直接返回 (chapter, id)；
//  2. 镜头类 → 直接返回 (shot, id)；
//  3. 图片类 → 需要再查一次图片表，拿到「图片属于哪个资产」。
//
// 第 3 类是唯一需要额外查询的分支，因此按 relation_type 分组批量查，
// 避免每个任务一次往返。
func (s *TaskStore) resolveNavigation(ctx context.Context, links map[string]*taskLinkRow) (map[string][2]string, error) {
	out := make(map[string][2]string, len(links))

	imageIDs := make(map[string][]int)
	imageTasks := make(map[string][]string)
	var frameImageIDs []int
	var frameImageTasks []string

	for taskID, link := range links {
		if link.RelationType == nil || link.RelationEntityID == nil {
			continue
		}
		relationType := *link.RelationType
		relationID := *link.RelationEntityID

		if navigateType, ok := navigateChapterRelationTypes[relationType]; ok {
			out[taskID] = [2]string{navigateType, relationID}
			continue
		}
		if navigateType, ok := navigateShotRelationTypes[relationType]; ok {
			out[taskID] = [2]string{navigateType, relationID}
			continue
		}
		numericID, err := strconv.Atoi(relationID)
		if err != nil {
			continue
		}
		if relationType == "shot_frame_image" {
			frameImageIDs = append(frameImageIDs, numericID)
			frameImageTasks = append(frameImageTasks, taskID)
			continue
		}
		if _, ok := navigateImageRelations[relationType]; ok {
			imageIDs[relationType] = append(imageIDs[relationType], numericID)
			imageTasks[relationType] = append(imageTasks[relationType], taskID)
		}
	}

	// 分镜帧图 → shot_detail_id 即 shot_id（两者共享主键）。
	if len(frameImageIDs) > 0 {
		placeholders := make([]string, len(frameImageIDs))
		args := make([]any, len(frameImageIDs))
		for i, id := range frameImageIDs {
			placeholders[i] = "?"
			args[i] = id
		}
		rows, err := s.db.QueryContext(ctx,
			"SELECT id, shot_detail_id FROM shot_frame_images WHERE id IN ("+strings.Join(placeholders, ",")+")",
			args...,
		)
		if err != nil {
			return nil, err
		}
		frameMap := make(map[int]string, len(frameImageIDs))
		for rows.Next() {
			var id int
			var shotID string
			if err := rows.Scan(&id, &shotID); err != nil {
				rows.Close()
				return nil, err
			}
			frameMap[id] = shotID
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
		for i, taskID := range frameImageTasks {
			if shotID, ok := frameMap[frameImageIDs[i]]; ok && shotID != "" {
				out[taskID] = [2]string{"shot", shotID}
			}
		}
	}

	// 图片 → 拥有者（actor/scene/prop/costume/character）。
	for relationType, ids := range imageIDs {
		spec := navigateImageRelations[relationType]
		placeholders := make([]string, len(ids))
		args := make([]any, len(ids))
		for i, id := range ids {
			placeholders[i] = "?"
			args[i] = id
		}
		query := fmt.Sprintf(
			"SELECT id, %s FROM %s WHERE id IN (%s)",
			spec.ownerCol, spec.table, strings.Join(placeholders, ","),
		)
		rows, err := s.db.QueryContext(ctx, query, args...)
		if err != nil {
			return nil, err
		}
		ownerMap := make(map[int]string, len(ids))
		for rows.Next() {
			var id int
			var ownerID string
			if err := rows.Scan(&id, &ownerID); err != nil {
				rows.Close()
				return nil, err
			}
			ownerMap[id] = ownerID
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}

		taskIDsForType := imageTasks[relationType]
		for i, taskID := range taskIDsForType {
			if ownerID, ok := ownerMap[ids[i]]; ok && ownerID != "" {
				out[taskID] = [2]string{spec.navigateT, ownerID}
			}
		}
	}

	return out, nil
}

// elapsedMillisOf 计算累计耗时（与 Python 的 _elapsed_ms_from_datetimes 一致）。
func elapsedMillisOf(startedAt, finishedAt *time.Time) *int64 {
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
