// Package store 提供控制面需要的只读查询。
//
// 当前阶段刻意只做「按主键查一行」这类最简单、最容易与 Python 对齐的查询。
// 复杂的列表/聚合在切流前不碰：薄查询错了影响小，复杂查询错了会直接让页面空白。
package store

import (
	"context"
	"database/sql"
	"errors"
	"time"
)

// ErrNotFound 表示目标行不存在。
var ErrNotFound = errors.New("not found")

// User 对应 Python 侧的 `UserRead`。
//
// 字段类型与 nullable 必须与 OpenAPI 一致：
// `display_name` / `email` / `avatar_url` 可空，`is_active` 非空，
// `created_at` 在 Python 侧是 `datetime | None`。
type User struct {
	ID           int
	Username     string
	DisplayName  *string
	IsActive     bool
	Email        *string
	AvatarURL    *string
	AuthProvider string
	CreatedAt    *time.Time
}

// UserStore 读 users 表。
type UserStore struct {
	db *sql.DB
}

// NewUserStore 构造用户查询。
func NewUserStore(db *sql.DB) *UserStore {
	return &UserStore{db: db}
}

// GetByID 按主键读取用户。
//
// 只 select 需要的列，不用 `SELECT *`：users 表里有 password_hash，
// 多取一列就多一次「不小心把它序列化进响应」的机会。
func (s *UserStore) GetByID(ctx context.Context, id int) (*User, error) {
	const query = `
		SELECT id, username, display_name, is_active, email, avatar_url, auth_provider, created_at
		FROM users
		WHERE id = ?`

	var u User
	err := s.db.QueryRowContext(ctx, query, id).Scan(
		&u.ID,
		&u.Username,
		&u.DisplayName,
		&u.IsActive,
		&u.Email,
		&u.AvatarURL,
		&u.AuthProvider,
		&u.CreatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &u, nil
}
