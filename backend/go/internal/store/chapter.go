package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
)

// Chapter 对应 Python 的 `ChapterRead`。
type Chapter struct {
	ID              string
	ProjectID       string
	Index           int
	Title           string
	Summary         string
	RawText         string
	CondensedText   string
	StoryboardCount int
	Status          string
	// ShotCount 是聚合字段，不是 chapters 表的列 ——
	// 由 `shots` 按 chapter_id 分组统计后回填。
	ShotCount int
}

// ChapterListParams 是列表查询参数。
type ChapterListParams struct {
	WorkspaceID string
	ProjectID   *string
	Keyword     *string
	OrderField  string
	Desc        bool
	Page        int
	PageSize    int
}

// ChapterOrderFields 是允许排序的列（白名单，防注入）。
var ChapterOrderFields = map[string]string{
	"index":            "index",
	"title":            "title",
	"created_at":       "created_at",
	"updated_at":       "updated_at",
	"storyboard_count": "storyboard_count",
	"status":           "status",
}

// ChapterStore 读 chapters 表。
type ChapterStore struct {
	db *sql.DB
}

// NewChapterStore 构造章节查询。
func NewChapterStore(db *sql.DB) *ChapterStore {
	return &ChapterStore{db: db}
}

const chapterColumns = `
	c.id, c.project_id, c.` + "`index`" + `, c.title, c.summary,
	c.raw_text, c.condensed_text, c.storyboard_count, c.status`

// scanChapter 从一行扫描出 Chapter。
func scanChapter(scanner interface{ Scan(...any) error }) (*Chapter, error) {
	var c Chapter
	err := scanner.Scan(
		&c.ID, &c.ProjectID, &c.Index, &c.Title, &c.Summary,
		&c.RawText, &c.CondensedText, &c.StoryboardCount, &c.Status,
	)
	if err != nil {
		return nil, err
	}
	return &c, nil
}

// List 分页查询章节。
//
// 工作区过滤经 projects 关联：chapters 表没有 workspace_id 列，
// 它的归属由所属项目决定（与 Python 的 apply_chapter_workspace_filter 一致）。
func (s *ChapterStore) List(ctx context.Context, params ChapterListParams) ([]*Chapter, int, error) {
	where := []string{"p.workspace_id = ?"}
	args := []any{params.WorkspaceID}

	if params.ProjectID != nil && strings.TrimSpace(*params.ProjectID) != "" {
		where = append(where, "c.project_id = ?")
		args = append(args, strings.TrimSpace(*params.ProjectID))
	}
	if params.Keyword != nil && strings.TrimSpace(*params.Keyword) != "" {
		where = append(where, "(c.title LIKE ? OR c.summary LIKE ?)")
		pattern := "%" + strings.TrimSpace(*params.Keyword) + "%"
		args = append(args, pattern, pattern)
	}

	base := " FROM chapters c JOIN projects p ON p.id = c.project_id"
	whereSQL := " WHERE " + strings.Join(where, " AND ")

	var total int
	if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*)"+base+whereSQL, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	orderColumn, ok := ChapterOrderFields[params.OrderField]
	if !ok {
		orderColumn = "index"
	}
	direction := "ASC"
	if params.Desc {
		direction = "DESC"
	}
	offset := (params.Page - 1) * params.PageSize

	query := fmt.Sprintf(
		"SELECT %s%s%s ORDER BY c.`%s` %s LIMIT ? OFFSET ?",
		chapterColumns, base, whereSQL, orderColumn, direction,
	)
	rows, err := s.db.QueryContext(ctx, query, append(args, params.PageSize, offset)...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	items := make([]*Chapter, 0, params.PageSize)
	for rows.Next() {
		item, err := scanChapter(rows)
		if err != nil {
			return nil, 0, err
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, err
	}

	if err := s.attachShotCounts(ctx, items); err != nil {
		return nil, 0, err
	}
	return items, total, nil
}

// attachShotCounts 批量回填 shots 数量。
//
// 用一次 GROUP BY 查询而不是逐行 count：列表默认 10 条，逐行就是 10 次额外往返，
// 而这条接口会被前端在进入项目时立刻调用。
func (s *ChapterStore) attachShotCounts(ctx context.Context, items []*Chapter) error {
	if len(items) == 0 {
		return nil
	}
	ids := make([]any, 0, len(items))
	placeholders := make([]string, 0, len(items))
	for _, item := range items {
		ids = append(ids, item.ID)
		placeholders = append(placeholders, "?")
	}

	query := "SELECT chapter_id, COUNT(*) FROM shots WHERE chapter_id IN (" +
		strings.Join(placeholders, ",") + ") GROUP BY chapter_id"
	rows, err := s.db.QueryContext(ctx, query, ids...)
	if err != nil {
		return err
	}
	defer rows.Close()

	counts := make(map[string]int, len(items))
	for rows.Next() {
		var chapterID string
		var cnt int
		if err := rows.Scan(&chapterID, &cnt); err != nil {
			return err
		}
		counts[chapterID] = cnt
	}
	if err := rows.Err(); err != nil {
		return err
	}

	for _, item := range items {
		item.ShotCount = counts[item.ID]
	}
	return nil
}

// Get 按主键读取章节，并校验工作区归属（经 project 关联）+ 回填 shot_count。
func (s *ChapterStore) Get(ctx context.Context, id, workspaceID string) (*Chapter, error) {
	query := fmt.Sprintf(
		"SELECT %s FROM chapters c JOIN projects p ON p.id = c.project_id WHERE c.id = ? AND p.workspace_id = ?",
		chapterColumns,
	)
	item, err := scanChapter(s.db.QueryRowContext(ctx, query, id, workspaceID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}

	var count int
	if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM shots WHERE chapter_id = ?", id).Scan(&count); err != nil {
		return nil, err
	}
	item.ShotCount = count
	return item, nil
}
