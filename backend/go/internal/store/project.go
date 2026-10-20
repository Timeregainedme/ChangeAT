package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
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
	UseDialogAudioAsReference     bool
	Stats                         json.RawMessage
	WorkspaceID                   string
	CreatedBy                     *int
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
	use_dialog_audio_as_reference, stats, workspace_id, created_by`

// scanProject 从一行扫描出 Project。
func scanProject(scanner interface{ Scan(...any) error }) (*Project, error) {
	var p Project
	var stats []byte
	err := scanner.Scan(
		&p.ID, &p.Name, &p.Description, &p.Style, &p.VisualStyle,
		&p.Seed, &p.UnifyStyle, &p.Progress,
		&p.DefaultVideoRatio, &p.DefaultImageRatio, &p.DefaultImageResolutionProfile,
		&p.UseDialogAudioAsReference, &stats, &p.WorkspaceID, &p.CreatedBy,
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
