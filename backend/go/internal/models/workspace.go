// Package models 存放跨 store / handler 共享的枚举与领域常量。
package models

// WorkspaceRole 是工作区成员角色。
//
// 取值必须与 Python 的 `WorkspaceRole` 枚举逐字一致（owner/admin/editor/viewer）：
// 这些字符串直接存在 `workspace_members.role` 列里，两侧不一致会导致鉴权判定错位。
type WorkspaceRole string

const (
	RoleOwner  WorkspaceRole = "owner"
	RoleAdmin  WorkspaceRole = "admin"
	RoleEditor WorkspaceRole = "editor"
	RoleViewer WorkspaceRole = "viewer"
)

// Level 返回角色等级，用于「至少需要某角色」的比较。
//
// 与 Python 的 `_ROLE_LEVEL` 保持一致：viewer=1, editor=2, admin=3, owner=4。
func (r WorkspaceRole) Level() int {
	switch r {
	case RoleViewer:
		return 1
	case RoleEditor:
		return 2
	case RoleAdmin:
		return 3
	case RoleOwner:
		return 4
	default:
		return 0
	}
}

// CanWrite 表示是否具备内容写权限（editor 及以上）。
func (r WorkspaceRole) CanWrite() bool {
	return r.Level() >= RoleEditor.Level()
}
