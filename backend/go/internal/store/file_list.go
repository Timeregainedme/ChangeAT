package store

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// FileRow 对应 Python 的 `FileRead`（列表只需要这 5 个字段）。
type FileRow struct {
	ID        string
	Type      string
	Name      string
	Thumbnail string
	Tags      json.RawMessage
}

// FileListParams 是文件列表查询参数。
type FileListParams struct {
	WorkspaceID string
	// ProjectID 为空表示「全工作区」列表；非空时按 file_usages 限定到该项目。
	ProjectID    *string
	ChapterTitle *string
	ShotTitle    *string
	Keyword      *string
	OrderField   string
	Desc         bool
	Page         int
	PageSize     int
}

// FileOrderFields 是允许排序的列（白名单，防注入）。
var FileOrderFields = map[string]string{
	"name":       "name",
	"created_at": "created_at",
	"updated_at": "updated_at",
}

// FileStore.List 分页查询文件。
//
// 两条查询路径与 Python 一致：
//  1. 无 project_id → 全工作区，用 EXISTS(file_usages ⋈ projects) 判定归属；
//  2. 有 project_id → 按 file_usages 限定范围，可再用章节/镜头标题收窄。
//
// 为什么不用「先查 usage 再查文件」的两段式：
// Python 侧用子查询 + group by 是因为 ORM 写起来方便；SQL 里一次 JOIN + GROUP BY
// 同样能表达，且只往返一次。语义必须一致：**同一文件去重、按排序键取 MAX**。
func (s *FileStore) List(ctx context.Context, params FileListParams) ([]*FileRow, int, error) {
	orderColumn, ok := FileOrderFields[params.OrderField]
	if !ok {
		orderColumn = "created_at"
	}
	direction := "ASC"
	if params.Desc {
		direction = "DESC"
	}

	if params.ProjectID != nil && *params.ProjectID != "" {
		return s.listByProject(ctx, params, orderColumn, direction)
	}
	return s.listByWorkspace(ctx, params, orderColumn, direction)
}

// listByWorkspace 查询当前工作区的全部文件。
func (s *FileStore) listByWorkspace(
	ctx context.Context,
	params FileListParams,
	orderColumn, direction string,
) ([]*FileRow, int, error) {
	where := []string{`EXISTS (
		SELECT 1 FROM file_usages u
		JOIN projects p ON p.id = u.project_id
		WHERE u.file_id = f.id AND p.workspace_id = ?
	)`}
	args := []any{params.WorkspaceID}

	if params.Keyword != nil && strings.TrimSpace(*params.Keyword) != "" {
		where = append(where, "f.name LIKE ?")
		args = append(args, "%"+strings.TrimSpace(*params.Keyword)+"%")
	}

	whereSQL := " WHERE " + strings.Join(where, " AND ")
	from := " FROM files f"

	var total int
	if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*)"+from+whereSQL, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	query := fmt.Sprintf(
		"SELECT f.id, f.type, f.name, f.thumbnail, f.tags%s%s ORDER BY f.%s %s LIMIT ? OFFSET ?",
		from, whereSQL, orderColumn, direction,
	)
	items, err := s.queryFiles(ctx, query, append(args, params.PageSize, (params.Page-1)*params.PageSize)...)
	if err != nil {
		return nil, 0, err
	}
	return items, total, nil
}

// listByProject 按项目范围查询文件。
func (s *FileStore) listByProject(
	ctx context.Context,
	params FileListParams,
	orderColumn, direction string,
) ([]*FileRow, int, error) {
	where := []string{"u.project_id = ?"}
	args := []any{*params.ProjectID}

	// 归属校验：project_id 来自 query，没有 router 级守卫拦截。
	// 不校验的话，传别家 project_id 就能列出对方全部文件。
	where = append(where, `EXISTS (
		SELECT 1 FROM projects p WHERE p.id = u.project_id AND p.workspace_id = ?
	)`)
	args = append(args, params.WorkspaceID)

	// 章节/镜头标题过滤，与 Python 的 _scope_filters 三个分支逐条对齐。
	rawChapter, rawShot := "", ""
	if params.ChapterTitle != nil {
		rawChapter = strings.TrimSpace(*params.ChapterTitle)
	}
	if params.ShotTitle != nil {
		rawShot = strings.TrimSpace(*params.ShotTitle)
	}

	switch {
	case rawChapter != "" && rawShot != "":
		where = append(where, `u.shot_id IN (
			SELECT s.id FROM shots s JOIN chapters c ON c.id = s.chapter_id
			WHERE c.project_id = ? AND c.title = ? AND s.title = ?
		)`)
		args = append(args, *params.ProjectID, rawChapter, rawShot)
	case rawChapter != "":
		where = append(where, `(
			u.chapter_id IN (SELECT c.id FROM chapters c WHERE c.project_id = ? AND c.title = ?)
			OR u.shot_id IN (
				SELECT s.id FROM shots s JOIN chapters c ON c.id = s.chapter_id
				WHERE c.project_id = ? AND c.title = ?
			)
		)`)
		args = append(args, *params.ProjectID, rawChapter, *params.ProjectID, rawChapter)
	case rawShot != "":
		where = append(where, `u.shot_id IN (
			SELECT s.id FROM shots s JOIN chapters c ON c.id = s.chapter_id
			WHERE c.project_id = ? AND s.title = ?
		)`)
		args = append(args, *params.ProjectID, rawShot)
	}

	if params.Keyword != nil && strings.TrimSpace(*params.Keyword) != "" {
		where = append(where, "f.name LIKE ?")
		args = append(args, "%"+strings.TrimSpace(*params.Keyword)+"%")
	}

	from := " FROM files f JOIN file_usages u ON u.file_id = f.id"
	whereSQL := " WHERE " + strings.Join(where, " AND ")

	// 一个文件可能有多条 usage，必须 DISTINCT，否则 total 与列表都会重复。
	var total int
	countQuery := "SELECT COUNT(DISTINCT f.id)" + from + whereSQL
	if err := s.db.QueryRowContext(ctx, countQuery, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	// 与 Python 一致：按 MAX(排序列) 排序后分组去重。
	query := fmt.Sprintf(
		"SELECT f.id, f.type, f.name, f.thumbnail, f.tags%s%s GROUP BY f.id ORDER BY MAX(f.%s) %s LIMIT ? OFFSET ?",
		from, whereSQL, orderColumn, direction,
	)
	items, err := s.queryFiles(ctx, query, append(args, params.PageSize, (params.Page-1)*params.PageSize)...)
	if err != nil {
		return nil, 0, err
	}
	return items, total, nil
}

// queryFiles 执行查询并扫描文件行（只负责取行，计数由调用方另行查询）。
func (s *FileStore) queryFiles(ctx context.Context, query string, args ...any) ([]*FileRow, error) {
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]*FileRow, 0, 16)
	for rows.Next() {
		var f FileRow
		var tags []byte
		if err := rows.Scan(&f.ID, &f.Type, &f.Name, &f.Thumbnail, &tags); err != nil {
			return nil, err
		}
		if len(tags) > 0 {
			f.Tags = json.RawMessage(tags)
		} else {
			f.Tags = json.RawMessage("[]")
		}
		items = append(items, &f)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return items, nil
}
