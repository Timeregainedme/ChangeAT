package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"
)

// ShotRow 对应 Python 的 `ShotRead`（含 extraction 摘要）。
type ShotRow struct {
	ID                   string
	ChapterID            string
	Index                int
	Title                string
	Thumbnail            string
	Status               string
	SkipExtraction       bool
	ScriptExcerpt        string
	GeneratedVideoFileID *string
	GeneratedAudioFileID *string
	LastExtractedAt      *time.Time

	// 以下由两张候选表聚合得出（见 loadExtractionCounts）
	AssetCandidateTotal    int
	DialogueCandidateTotal int
	PendingAssetCount      int
	PendingDialogueCount   int
}

// ShotListParams 是镜头列表参数。
type ShotListParams struct {
	WorkspaceID string
	ChapterID   *string
	Keyword     *string
	OrderField  string
	Desc        bool
	Page        int
	PageSize    int
}

// ShotOrderFields 是允许排序的列（白名单，防注入）。
var ShotOrderFields = map[string]string{
	"index":      "index",
	"title":      "title",
	"status":     "status",
	"created_at": "created_at",
	"updated_at": "updated_at",
}

const shotColumns = `
	s.id, s.chapter_id, s.` + "`index`" + `, s.title, s.thumbnail, s.status,
	s.skip_extraction, s.script_excerpt, s.generated_video_file_id,
	s.generated_audio_file_id, s.last_extracted_at`

// ShotStore 读 shots 表。
type ShotStore struct {
	db *sql.DB
}

// NewShotStore 构造镜头查询。
func NewShotStore(db *sql.DB) *ShotStore {
	return &ShotStore{db: db}
}

// scanShot 从一行扫描出 ShotRow。
func scanShot(scanner interface{ Scan(...any) error }) (*ShotRow, error) {
	var s ShotRow
	err := scanner.Scan(
		&s.ID, &s.ChapterID, &s.Index, &s.Title, &s.Thumbnail, &s.Status,
		&s.SkipExtraction, &s.ScriptExcerpt, &s.GeneratedVideoFileID,
		&s.GeneratedAudioFileID, &s.LastExtractedAt,
	)
	if err != nil {
		return nil, err
	}
	return &s, nil
}

// List 分页查询镜头。
//
// 归属经 chapters → projects 过滤：shots 表没有 workspace_id 列，
// 与 Python 的 list_paginated 一致。
func (s *ShotStore) List(ctx context.Context, params ShotListParams) ([]*ShotRow, int, error) {
	where := []string{"p.workspace_id = ?"}
	args := []any{params.WorkspaceID}

	if params.ChapterID != nil && strings.TrimSpace(*params.ChapterID) != "" {
		where = append(where, "s.chapter_id = ?")
		args = append(args, strings.TrimSpace(*params.ChapterID))
	}
	if params.Keyword != nil && strings.TrimSpace(*params.Keyword) != "" {
		where = append(where, "(s.title LIKE ? OR s.script_excerpt LIKE ?)")
		pattern := "%" + strings.TrimSpace(*params.Keyword) + "%"
		args = append(args, pattern, pattern)
	}

	from := " FROM shots s JOIN chapters c ON c.id = s.chapter_id JOIN projects p ON p.id = c.project_id"
	whereSQL := " WHERE " + strings.Join(where, " AND ")

	var total int
	if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*)"+from+whereSQL, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	orderColumn, ok := ShotOrderFields[params.OrderField]
	if !ok {
		orderColumn = "index"
	}
	direction := "ASC"
	if params.Desc {
		direction = "DESC"
	}

	query := fmt.Sprintf(
		"SELECT %s%s%s ORDER BY s.`%s` %s LIMIT ? OFFSET ?",
		shotColumns, from, whereSQL, orderColumn, direction,
	)
	rows, err := s.db.QueryContext(ctx, query, append(args, params.PageSize, (params.Page-1)*params.PageSize)...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	items := make([]*ShotRow, 0, params.PageSize)
	for rows.Next() {
		item, err := scanShot(rows)
		if err != nil {
			return nil, 0, err
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, err
	}

	if err := s.loadExtractionCounts(ctx, items); err != nil {
		return nil, 0, err
	}
	return items, total, nil
}

// Get 按主键读取镜头并校验归属。
func (s *ShotStore) Get(ctx context.Context, shotID, workspaceID string) (*ShotRow, error) {
	query := fmt.Sprintf(
		"SELECT %s FROM shots s JOIN chapters c ON c.id = s.chapter_id JOIN projects p ON p.id = c.project_id WHERE s.id = ? AND p.workspace_id = ?",
		shotColumns,
	)
	item, err := scanShot(s.db.QueryRowContext(ctx, query, shotID, workspaceID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if err := s.loadExtractionCounts(ctx, []*ShotRow{item}); err != nil {
		return nil, err
	}
	return item, nil
}

// loadExtractionCounts 批量聚合两张候选表的数量。
//
// 用一次 GROUP BY 各查一次，而不是逐镜头 count ——
// 列表默认 10 条，逐条就是 20 次额外往返，而镜头列表在进入章节时立刻被调用。
func (s *ShotStore) loadExtractionCounts(ctx context.Context, items []*ShotRow) error {
	if len(items) == 0 {
		return nil
	}
	ids := make([]any, 0, len(items))
	placeholders := make([]string, 0, len(items))
	for _, item := range items {
		ids = append(ids, item.ID)
		placeholders = append(placeholders, "?")
	}
	in := strings.Join(placeholders, ",")

	// 资产候选
	assetQuery := fmt.Sprintf(`
		SELECT shot_id, COUNT(*), SUM(CASE WHEN candidate_status = 'pending' THEN 1 ELSE 0 END)
		FROM shot_extracted_candidates WHERE shot_id IN (%s) GROUP BY shot_id`, in)
	if err := s.scanCounts(ctx, assetQuery, ids, items, true); err != nil {
		return err
	}

	// 对白候选
	dialogueQuery := fmt.Sprintf(`
		SELECT shot_id, COUNT(*), SUM(CASE WHEN candidate_status = 'pending' THEN 1 ELSE 0 END)
		FROM shot_extracted_dialogue_candidates WHERE shot_id IN (%s) GROUP BY shot_id`, in)
	if err := s.scanCounts(ctx, dialogueQuery, ids, items, false); err != nil {
		return err
	}

	return nil
}

// scanCounts 把聚合结果写入 items。
func (s *ShotStore) scanCounts(
	ctx context.Context,
	query string,
	args []any,
	items []*ShotRow,
	asset bool,
) error {
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return err
	}
	defer rows.Close()

	byID := make(map[string][2]int, len(items))
	for rows.Next() {
		var id string
		var total int
		var pending sql.NullInt64
		if err := rows.Scan(&id, &total, &pending); err != nil {
			return err
		}
		byID[id] = [2]int{total, int(pending.Int64)}
	}
	if err := rows.Err(); err != nil {
		return err
	}

	for _, item := range items {
		counts := byID[item.ID]
		if asset {
			item.AssetCandidateTotal = counts[0]
			item.PendingAssetCount = counts[1]
		} else {
			item.DialogueCandidateTotal = counts[0]
			item.PendingDialogueCount = counts[1]
		}
	}
	return nil
}

// ExtractionState 计算提取状态摘要。
//
// 必须与 Python 的 `_build_extraction_state` 逐分支一致：
// skipped → not_extracted → extracted_empty → extracted_pending → extracted_resolved。
// 顺序不能变：例如「已跳过」优先于「未提取」，否则跳过提取的镜头会显示成待提取。
func (s *ShotRow) ExtractionState() string {
	if s.SkipExtraction {
		return "skipped"
	}
	if s.LastExtractedAt == nil {
		return "not_extracted"
	}
	if s.AssetCandidateTotal == 0 && s.DialogueCandidateTotal == 0 {
		return "extracted_empty"
	}
	if s.PendingAssetCount > 0 || s.PendingDialogueCount > 0 {
		return "extracted_pending"
	}
	return "extracted_resolved"
}
