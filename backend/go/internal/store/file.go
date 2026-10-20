package store

import (
	"context"
	"database/sql"
	"errors"
)

// FileItem 是下载所需的文件元数据子集。
//
// 只取三列：id 用于日志、thumbnail 决定是否 302、name 用于兜底响应头。
// 不取 storage_key 及其他列：本接口是匿名可访问的，少读一列就少一处泄露面。
type FileItem struct {
	ID        string
	Name      string
	Thumbnail string
}

// FileStore 读 files 表。
type FileStore struct {
	db *sql.DB
}

// NewFileStore 构造文件查询。
func NewFileStore(db *sql.DB) *FileStore {
	return &FileStore{db: db}
}

// GetDownloadMeta 读取下载所需的元数据。
func (s *FileStore) GetDownloadMeta(ctx context.Context, id string) (*FileItem, error) {
	const query = `SELECT id, name, thumbnail FROM files WHERE id = ?`

	var item FileItem
	err := s.db.QueryRowContext(ctx, query, id).Scan(&item.ID, &item.Name, &item.Thumbnail)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &item, nil
}
