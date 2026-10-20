package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"
)

// GenerationTask 是任务状态查询需要的列。
//
// 不取 payload：它可能有几十 KB（图片 base64 引用、完整分镜），
// 而状态轮询是高频接口，只读状态列可以显著降低 IO。
type GenerationTask struct {
	ID                string
	WorkspaceID       string
	Status            string
	Progress          int
	CancelRequested   bool
	CancelRequestedAt *time.Time
	StartedAt         *time.Time
	FinishedAt        *time.Time
	Result            json.RawMessage
	Error             string
}

// TaskStore 读 generation_tasks 表。
type TaskStore struct {
	db *sql.DB
}

// NewTaskStore 构造任务查询。
func NewTaskStore(db *sql.DB) *TaskStore {
	return &TaskStore{db: db}
}

// GetStatus 读取状态查询所需的列。
//
// 查询本身不带 workspace 条件：调用方需要区分「任务不存在」与「任务不属于当前工作区」，
// 但**对外必须统一回 404**（见 handler 注释）。把两段逻辑分开，
// 是为了让「归属校验」这件事在 handler 里只写一次，而不是散落在每条 SQL 里。
func (s *TaskStore) GetStatus(ctx context.Context, id string) (*GenerationTask, error) {
	const query = `
		SELECT id, workspace_id, status, progress, cancel_requested,
		       cancel_requested_at, started_at, finished_at
		FROM generation_tasks
		WHERE id = ?`

	var t GenerationTask
	err := s.db.QueryRowContext(ctx, query, id).Scan(
		&t.ID,
		&t.WorkspaceID,
		&t.Status,
		&t.Progress,
		&t.CancelRequested,
		&t.CancelRequestedAt,
		&t.StartedAt,
		&t.FinishedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &t, nil
}

// GetResult 读取结果查询所需的列（在状态列基础上多取 result / error）。
func (s *TaskStore) GetResult(ctx context.Context, id string) (*GenerationTask, error) {
	const query = `
		SELECT id, workspace_id, status, progress, cancel_requested,
		       cancel_requested_at, started_at, finished_at, result, error
		FROM generation_tasks
		WHERE id = ?`

	var t GenerationTask
	var result []byte
	var errText sql.NullString
	err := s.db.QueryRowContext(ctx, query, id).Scan(
		&t.ID,
		&t.WorkspaceID,
		&t.Status,
		&t.Progress,
		&t.CancelRequested,
		&t.CancelRequestedAt,
		&t.StartedAt,
		&t.FinishedAt,
		&result,
		&errText,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if len(result) > 0 {
		t.Result = json.RawMessage(result)
	}
	t.Error = errText.String
	return &t, nil
}
