package store

import (
	"context"
	"database/sql"
	"errors"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/models"
)

// WorkspaceStore 解析请求所属工作区。
type WorkspaceStore struct {
	db *sql.DB
}

// NewWorkspaceStore 构造工作区查询。
func NewWorkspaceStore(db *sql.DB) *WorkspaceStore {
	return &WorkspaceStore{db: db}
}

// Resolve 解析用户当前所在的工作区。
//
// 与 Python 的 get_workspace_context 对齐：
//  1. 显式指定（X-Workspace-ID）→ 必须是该用户的在岗成员，否则 ErrNotFound。
//     **不区分「工作区不存在」与「不是成员」**：区分会让别家工作区 ID 变成可探测面。
//  2. 未指定 → 取该用户加入的第一个工作区（单工作区用户因此零改动可用）。
//
// 返回 models.WorkspaceRole 便于后续做写权限判断。
func (s *WorkspaceStore) Resolve(ctx context.Context, userID int, requestedID string) (workspaceID string, role models.WorkspaceRole, err error) {
	if requestedID != "" {
		const query = `
			SELECT wm.workspace_id, wm.role
			FROM workspace_members wm
			JOIN workspaces w ON w.id = wm.workspace_id
			WHERE wm.workspace_id = ? AND wm.user_id = ? AND wm.is_active = 1 AND w.is_active = 1
			LIMIT 1`
		var r string
		if err := s.db.QueryRowContext(ctx, query, requestedID, userID).Scan(&workspaceID, &r); err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				return "", "", ErrNotFound
			}
			return "", "", err
		}
		return workspaceID, models.WorkspaceRole(r), nil
	}

	const query = `
		SELECT wm.workspace_id, wm.role
		FROM workspace_members wm
		JOIN workspaces w ON w.id = wm.workspace_id
		WHERE wm.user_id = ? AND wm.is_active = 1 AND w.is_active = 1
		ORDER BY wm.id
		LIMIT 1`
	var r string
	if err := s.db.QueryRowContext(ctx, query, userID).Scan(&workspaceID, &r); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return "", "", ErrNotFound
		}
		return "", "", err
	}
	return workspaceID, models.WorkspaceRole(r), nil
}
