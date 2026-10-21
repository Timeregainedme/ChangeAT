package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

// ShotFrameImageRow 对应 Python 的 `ShotFrameImageRead`。
type ShotFrameImageRow struct {
	ID           int
	ShotDetailID string
	FrameType    string
	FileID       *string
	Width        *int
	Height       *int
	Format       string
}

// FrameImageListParams 是帧图列表参数。
type FrameImageListParams struct {
	WorkspaceID  string
	ShotDetailID *string
	OrderField   string
	Desc         bool
	Page         int
	PageSize     int
}

// FrameImageOrderFields 是允许排序的列（白名单）。
var FrameImageOrderFields = map[string]string{
	"id":         "id",
	"created_at": "created_at",
	"updated_at": "updated_at",
}

// FrameImageStore 读 shot_frame_images 表。
type FrameImageStore struct {
	db *sql.DB
}

// NewFrameImageStore 构造帧图查询。
func NewFrameImageStore(db *sql.DB) *FrameImageStore {
	return &FrameImageStore{db: db}
}

const frameImageColumns = `
	fi.id, fi.shot_detail_id, fi.frame_type, fi.file_id, fi.width, fi.height, fi.format`

// List 分页查询帧图。
//
// 归属链：shot_frame_images → shot_details → shots → chapters → projects。
// shot_details 与 shots 共享主键，但仍显式 join 以保持链路可读。
func (s *FrameImageStore) List(ctx context.Context, params FrameImageListParams) ([]*ShotFrameImageRow, int, error) {
	where := []string{"p.workspace_id = ?"}
	args := []any{params.WorkspaceID}

	if params.ShotDetailID != nil && strings.TrimSpace(*params.ShotDetailID) != "" {
		where = append(where, "fi.shot_detail_id = ?")
		args = append(args, strings.TrimSpace(*params.ShotDetailID))
	}

	from := ` FROM shot_frame_images fi
		JOIN shot_details sd ON sd.id = fi.shot_detail_id
		JOIN shots s ON s.id = sd.id
		JOIN chapters c ON c.id = s.chapter_id
		JOIN projects p ON p.id = c.project_id`
	whereSQL := " WHERE " + strings.Join(where, " AND ")

	var total int
	if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*)"+from+whereSQL, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	orderColumn, ok := FrameImageOrderFields[params.OrderField]
	if !ok {
		orderColumn = "id"
	}
	direction := "ASC"
	if params.Desc {
		direction = "DESC"
	}

	query := fmt.Sprintf(
		"SELECT %s%s%s ORDER BY fi.%s %s LIMIT ? OFFSET ?",
		frameImageColumns, from, whereSQL, orderColumn, direction,
	)
	rows, err := s.db.QueryContext(ctx, query, append(args, params.PageSize, (params.Page-1)*params.PageSize)...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	items := make([]*ShotFrameImageRow, 0, params.PageSize)
	for rows.Next() {
		var f ShotFrameImageRow
		if err := rows.Scan(&f.ID, &f.ShotDetailID, &f.FrameType, &f.FileID, &f.Width, &f.Height, &f.Format); err != nil {
			return nil, 0, err
		}
		items = append(items, &f)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, err
	}
	return items, total, nil
}

// ShotDetailRow 对应 Python 的 `ShotDetailRead`。
type ShotDetailRow struct {
	ID                 string
	CameraShot         string
	Angle              string
	Movement           string
	SceneID            *string
	Duration           int
	OverrideVideoRatio *string
	MoodTags           json.RawMessage
	Atmosphere         string
	FollowAtmosphere   bool
	HasBGM             bool
	VFXType            string
	VFXNote            string
	Description        string
	ActionBeats        json.RawMessage
	PromptTemplateID   *string
	FirstFramePrompt   string
	LastFramePrompt    string
	KeyFramePrompt     string
}

// ShotDetailStore 读 shot_details 表。
type ShotDetailStore struct {
	db *sql.DB
}

// NewShotDetailStore 构造镜头细节查询。
func NewShotDetailStore(db *sql.DB) *ShotDetailStore {
	return &ShotDetailStore{db: db}
}

// Get 按主键读取镜头细节并校验归属。
//
// shot_details 与 shots 共享主键，路径里的 shot_id 即细节 ID。
func (s *ShotDetailStore) Get(ctx context.Context, shotID, workspaceID string) (*ShotDetailRow, error) {
	const query = `
		SELECT sd.id, sd.camera_shot, sd.angle, sd.movement, sd.scene_id, sd.duration,
		       sd.override_video_ratio, sd.mood_tags, sd.atmosphere, sd.follow_atmosphere,
		       sd.has_bgm, sd.vfx_type, sd.vfx_note, sd.description, sd.action_beats,
		       sd.prompt_template_id, sd.first_frame_prompt, sd.last_frame_prompt, sd.key_frame_prompt
		FROM shot_details sd
		JOIN shots s ON s.id = sd.id
		JOIN chapters c ON c.id = s.chapter_id
		JOIN projects p ON p.id = c.project_id
		WHERE sd.id = ? AND p.workspace_id = ?`

	var d ShotDetailRow
	var moodTags, actionBeats []byte
	err := s.db.QueryRowContext(ctx, query, shotID, workspaceID).Scan(
		&d.ID, &d.CameraShot, &d.Angle, &d.Movement, &d.SceneID, &d.Duration,
		&d.OverrideVideoRatio, &moodTags, &d.Atmosphere, &d.FollowAtmosphere,
		&d.HasBGM, &d.VFXType, &d.VFXNote, &d.Description, &actionBeats,
		&d.PromptTemplateID, &d.FirstFramePrompt, &d.LastFramePrompt, &d.KeyFramePrompt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if len(moodTags) > 0 {
		d.MoodTags = json.RawMessage(moodTags)
	} else {
		d.MoodTags = json.RawMessage("[]")
	}
	if len(actionBeats) > 0 {
		d.ActionBeats = json.RawMessage(actionBeats)
	} else {
		d.ActionBeats = json.RawMessage("[]")
	}
	return &d, nil
}

// TaskLinkRow 对应 Python 的 `GenerationTaskLinkRead`。
type TaskLinkRow struct {
	ID               int
	TaskID           string
	ResourceType     string
	RelationType     string
	RelationEntityID string
	FileID           *string
	Status           string
}

// TaskLinkListParams 是任务关联列表参数。
type TaskLinkListParams struct {
	WorkspaceID      string
	ResourceType     *string
	RelationType     *string
	RelationEntityID *string
	Status           *string
	TaskID           *string
	OrderField       string
	Desc             bool
	Page             int
	PageSize         int
}

// TaskLinkOrderFields 是允许排序的列（白名单）。
var TaskLinkOrderFields = map[string]string{
	"id":         "id",
	"status":     "status",
	"created_at": "created_at",
	"updated_at": "updated_at",
}

// ListTaskLinks 分页查询任务关联。
//
// 关联行无 workspace_id，归属经 generation_tasks 继承 ——
// 所有过滤参数可选，不传即全表，必须显式 join 过滤。
func (s *TaskStore) ListTaskLinks(ctx context.Context, params TaskLinkListParams) ([]*TaskLinkRow, int, error) {
	where := []string{"t.workspace_id = ?"}
	args := []any{params.WorkspaceID}

	for _, f := range []struct {
		value *string
		col   string
	}{
		{params.ResourceType, "l.resource_type"},
		{params.RelationType, "l.relation_type"},
		{params.RelationEntityID, "l.relation_entity_id"},
		{params.Status, "l.status"},
		{params.TaskID, "l.task_id"},
	} {
		if f.value != nil && strings.TrimSpace(*f.value) != "" {
			where = append(where, f.col+" = ?")
			args = append(args, strings.TrimSpace(*f.value))
		}
	}

	from := " FROM generation_task_links l JOIN generation_tasks t ON t.id = l.task_id"
	whereSQL := " WHERE " + strings.Join(where, " AND ")

	var total int
	if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*)"+from+whereSQL, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	orderColumn, ok := TaskLinkOrderFields[params.OrderField]
	if !ok {
		orderColumn = "updated_at"
	}
	direction := "DESC"
	if !params.Desc {
		direction = "ASC"
	}

	query := fmt.Sprintf(
		"SELECT l.id, l.task_id, l.resource_type, l.relation_type, l.relation_entity_id, l.file_id, l.status%s%s ORDER BY l.%s %s LIMIT ? OFFSET ?",
		from, whereSQL, orderColumn, direction,
	)
	rows, err := s.db.QueryContext(ctx, query, append(args, params.PageSize, (params.Page-1)*params.PageSize)...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	items := make([]*TaskLinkRow, 0, params.PageSize)
	for rows.Next() {
		var l TaskLinkRow
		if err := rows.Scan(&l.ID, &l.TaskID, &l.ResourceType, &l.RelationType,
			&l.RelationEntityID, &l.FileID, &l.Status); err != nil {
			return nil, 0, err
		}
		items = append(items, &l)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, err
	}
	return items, total, nil
}
