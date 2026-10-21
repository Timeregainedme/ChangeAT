package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
)

// Project 对应 Python 的 `ProjectRead`。
//
// 字段顺序与 channel 无关，但**字段集合必须精确**：多一个字段会让前端类型校验
// 出现未知属性，少一个会让页面读到 undefined。
type Project struct {
	ID                            string
	Name                          string
	Description                   string
	Style                         string
	VisualStyle                   string
	Seed                          int
	UnifyStyle                    bool
	Progress                      int
	DefaultVideoRatio             *string
	DefaultImageRatio             *string
	DefaultImageResolutionProfile *string
	DefaultVideoResolution        *string
	UseDialogAudioAsReference     bool
	Stats                         json.RawMessage
	WorkspaceID                   string
	CreatedBy                     *int
	UpdatedAt                     time.Time
}

// ProjectStats 是项目体量聚合，由实时查询得出而不是读 projects.stats 列。
//
// 为什么不用存量 JSON 列：那一列从建表起就没有任何写入方，全库都是 {}，
// 前端拿到的统计永远是 0。聚合口径与页面语义对齐：
//   - chapters：章节数
//   - roles：角色数（characters，项目内唯一）
//   - scenes/props：项目关联表里去重后的资产数（同一场景可被多镜头关联）
type ProjectStats struct {
	Chapters int `json:"chapters"`
	Roles    int `json:"roles"`
	Scenes   int `json:"scenes"`
	Props    int `json:"props"`
}

// ProjectListParams 是列表查询参数。
type ProjectListParams struct {
	WorkspaceID string
	Keyword     *string
	// OrderField 必须是白名单内的列名（见 ProjectOrderFields），调用方负责校验。
	OrderField string
	Desc       bool
	Page       int
	PageSize   int
}

// ProjectOrderFields 是允许排序的列。
//
// 排序字段来自 query 参数，直接拼进 SQL 就是注入面。
// 用白名单映射而不是转义：转义仍然可能拼出非法列名，白名单让「只允许这些」成为事实。
var ProjectOrderFields = map[string]string{
	"name":       "name",
	"created_at": "created_at",
	"updated_at": "updated_at",
	"progress":   "progress",
}

// ProjectStore 读 projects 表。
type ProjectStore struct {
	db *sql.DB
}

// NewProjectStore 构造项目查询。
func NewProjectStore(db *sql.DB) *ProjectStore {
	return &ProjectStore{db: db}
}

const projectColumns = `
	id, name, description, style, visual_style, seed, unify_style, progress,
	default_video_ratio, default_image_ratio, default_image_resolution_profile,
	default_video_resolution, use_dialog_audio_as_reference, stats, workspace_id, created_by, updated_at`

// scanProject 从一行扫描出 Project。
func scanProject(scanner interface{ Scan(...any) error }) (*Project, error) {
	var p Project
	var stats []byte
	err := scanner.Scan(
		&p.ID, &p.Name, &p.Description, &p.Style, &p.VisualStyle,
		&p.Seed, &p.UnifyStyle, &p.Progress,
		&p.DefaultVideoRatio, &p.DefaultImageRatio, &p.DefaultImageResolutionProfile,
		&p.DefaultVideoResolution, &p.UseDialogAudioAsReference, &stats, &p.WorkspaceID,
		&p.CreatedBy, &p.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	if len(stats) > 0 {
		p.Stats = json.RawMessage(stats)
	} else {
		p.Stats = json.RawMessage("{}")
	}
	return &p, nil
}

// List 分页查询项目。
func (s *ProjectStore) List(ctx context.Context, params ProjectListParams) ([]*Project, int, error) {
	where := []string{"workspace_id = ?"}
	args := []any{params.WorkspaceID}

	if params.Keyword != nil && strings.TrimSpace(*params.Keyword) != "" {
		// 与 Python 的 apply_keyword_filter 一致：name/description 任一命中，大小写不敏感。
		// MySQL 的 utf8mb4_unicode_ci 排序规则本身不区分大小写，无需 LOWER()。
		where = append(where, "(name LIKE ? OR description LIKE ?)")
		pattern := "%" + strings.TrimSpace(*params.Keyword) + "%"
		args = append(args, pattern, pattern)
	}

	whereSQL := " WHERE " + strings.Join(where, " AND ")

	var total int
	if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM projects"+whereSQL, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	orderColumn, ok := ProjectOrderFields[params.OrderField]
	if !ok {
		orderColumn = "created_at"
	}
	direction := "ASC"
	if params.Desc {
		direction = "DESC"
	}
	offset := (params.Page - 1) * params.PageSize

	query := fmt.Sprintf(
		"SELECT %s FROM projects%s ORDER BY %s %s LIMIT ? OFFSET ?",
		projectColumns, whereSQL, orderColumn, direction,
	)
	rows, err := s.db.QueryContext(ctx, query, append(args, params.PageSize, offset)...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	items := make([]*Project, 0, params.PageSize)
	for rows.Next() {
		item, err := scanProject(rows)
		if err != nil {
			return nil, 0, err
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, err
	}
	return items, total, nil
}

// Get 按主键读取项目，并校验工作区归属。
//
// 归属条件直接写进 SQL（而不是查完再比）：少一次「忘记比较」的机会。
// 不属于当前工作区时返回 ErrNotFound，与「不存在」对外不可区分。
func (s *ProjectStore) Get(ctx context.Context, id, workspaceID string) (*Project, error) {
	query := fmt.Sprintf("SELECT %s FROM projects WHERE id = ? AND workspace_id = ?", projectColumns)
	item, err := scanProject(s.db.QueryRowContext(ctx, query, id, workspaceID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return item, nil
}

// inClause 生成 n 个占位符，用于 IN 查询。
func inClause(n int) string {
	parts := make([]string, n)
	for i := range parts {
		parts[i] = "?"
	}
	return strings.Join(parts, ",")
}

// countGroupedByProject 执行「按 project_id 分组计数」的查询，返回 project_id → 数量。
func (s *ProjectStore) countGroupedByProject(ctx context.Context, query string, projectIDs []string) (map[string]int, error) {
	args := make([]any, len(projectIDs))
	for i, id := range projectIDs {
		args[i] = id
	}
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make(map[string]int, len(projectIDs))
	for rows.Next() {
		var projectID string
		var count int
		if err := rows.Scan(&projectID, &count); err != nil {
			return nil, err
		}
		out[projectID] = count
	}
	return out, rows.Err()
}

// LoadStats 批量加载项目体量统计。
//
// 四条查询并发发出而不是逐项目查：列表页 10 个项目如果逐个查就是 40 次往返，
// 在 300ms 的国际链路上足以让页面明显变慢。
//
// 统计属于「锦上添花」：任一条查询失败就返回错误，由调用方决定降级
// （当前是保留存量 stats，不阻断列表）。
func (s *ProjectStore) LoadStats(ctx context.Context, projectIDs []string) (map[string]ProjectStats, error) {
	out := make(map[string]ProjectStats, len(projectIDs))
	if len(projectIDs) == 0 {
		return out, nil
	}

	placeholders := inClause(len(projectIDs))

	sources := map[string]string{
		"chapters": "SELECT project_id, COUNT(*) FROM chapters WHERE project_id IN (" + placeholders + ") GROUP BY project_id",
		"roles":    "SELECT project_id, COUNT(*) FROM characters WHERE project_id IN (" + placeholders + ") GROUP BY project_id",
		"scenes":   "SELECT project_id, COUNT(DISTINCT scene_id) FROM project_scene_links WHERE project_id IN (" + placeholders + ") GROUP BY project_id",
		"props":    "SELECT project_id, COUNT(DISTINCT prop_id) FROM project_prop_links WHERE project_id IN (" + placeholders + ") GROUP BY project_id",
	}

	type result struct {
		key   string
		count map[string]int
		err   error
	}
	results := make(chan result, len(sources))

	for key, query := range sources {
		go func(key, query string) {
			count, err := s.countGroupedByProject(ctx, query, projectIDs)
			results <- result{key: key, count: count, err: err}
		}(key, query)
	}

	collected := make(map[string]map[string]int, len(sources))
	for range sources {
		r := <-results
		if r.err != nil {
			return nil, r.err
		}
		collected[r.key] = r.count
	}

	for _, id := range projectIDs {
		out[id] = ProjectStats{
			Chapters: collected["chapters"][id],
			Roles:    collected["roles"][id],
			Scenes:   collected["scenes"][id],
			Props:    collected["props"][id],
		}
	}
	return out, nil
}

// StyleRow 是风格目录的一行（只取展示需要的字段）。
type StyleRow struct {
	VisualStyle string
	Name        string
	SortOrder   int
}

// ListStyleOptions 读取风格目录。
//
// 目录表由 Python 侧维护（首次访问会用内置枚举种子化），这里只读。
// 查询失败时调用方按「内置静态列表」降级，保证前端下拉永远不会空。
func (s *ProjectStore) ListStyleOptions(ctx context.Context) ([]StyleRow, error) {
	rows, err := s.db.QueryContext(
		ctx,
		"SELECT visual_style, name, sort_order FROM project_styles ORDER BY sort_order ASC, name ASC",
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]StyleRow, 0, 16)
	for rows.Next() {
		var row StyleRow
		if err := rows.Scan(&row.VisualStyle, &row.Name, &row.SortOrder); err != nil {
			return nil, err
		}
		items = append(items, row)
	}
	return items, rows.Err()
}
