package handler

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/timeregainedme/dyeingtime/backend/go/internal/middleware"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/response"
	"github.com/timeregainedme/dyeingtime/backend/go/internal/store"
)

// Shot 提供镜头相关只读接口。
type Shot struct {
	shots      *store.ShotStore
	details    *store.ShotDetailStore
	frames     *store.FrameImageStore
	workspaces *store.WorkspaceStore
}

// NewShot 构造镜头 handler。
func NewShot(
	shots *store.ShotStore,
	details *store.ShotDetailStore,
	frames *store.FrameImageStore,
	workspaces *store.WorkspaceStore,
) *Shot {
	return &Shot{shots: shots, details: details, frames: frames, workspaces: workspaces}
}

// extractionSummaryRead 对应 Python 的 `ShotExtractionSummaryRead`。
type extractionSummaryRead struct {
	State                  string  `json:"state"`
	HasExtracted           bool    `json:"has_extracted"`
	LastExtractedAt        *string `json:"last_extracted_at"`
	AssetCandidateTotal    int     `json:"asset_candidate_total"`
	DialogueCandidateTotal int     `json:"dialogue_candidate_total"`
	PendingAssetCount      int     `json:"pending_asset_count"`
	PendingDialogueCount   int     `json:"pending_dialogue_count"`
}

// shotRead 对应 Python 的 `ShotRead`。
type shotRead struct {
	ID                   string                `json:"id"`
	ChapterID            string                `json:"chapter_id"`
	Index                int                   `json:"index"`
	Title                string                `json:"title"`
	Thumbnail            string                `json:"thumbnail"`
	Status               string                `json:"status"`
	SkipExtraction       bool                  `json:"skip_extraction"`
	ScriptExcerpt        string                `json:"script_excerpt"`
	GeneratedVideoFileID *string               `json:"generated_video_file_id"`
	GeneratedAudioFileID *string               `json:"generated_audio_file_id"`
	LastExtractedAt      *string               `json:"last_extracted_at"`
	Extraction           extractionSummaryRead `json:"extraction"`
}

// frameImageRead 对应 Python 的 `ShotFrameImageRead`。
type frameImageRead struct {
	ID           int     `json:"id"`
	ShotDetailID string  `json:"shot_detail_id"`
	FrameType    string  `json:"frame_type"`
	FileID       *string `json:"file_id"`
	Width        *int    `json:"width"`
	Height       *int    `json:"height"`
	Format       string  `json:"format"`
}

// shotDetailRead 对应 Python 的 `ShotDetailRead`。
type shotDetailRead struct {
	ID                 string          `json:"id"`
	CameraShot         string          `json:"camera_shot"`
	Angle              string          `json:"angle"`
	Movement           string          `json:"movement"`
	SceneID            *string         `json:"scene_id"`
	Duration           int             `json:"duration"`
	OverrideVideoRatio *string         `json:"override_video_ratio"`
	MoodTags           json.RawMessage `json:"mood_tags"`
	Atmosphere         string          `json:"atmosphere"`
	FollowAtmosphere   bool            `json:"follow_atmosphere"`
	HasBGM             bool            `json:"has_bgm"`
	VFXType            string          `json:"vfx_type"`
	VFXNote            string          `json:"vfx_note"`
	ActionBeats        json.RawMessage `json:"action_beats"`
	FirstFramePrompt   string          `json:"first_frame_prompt"`
	LastFramePrompt    string          `json:"last_frame_prompt"`
	KeyFramePrompt     string          `json:"key_frame_prompt"`
}

// List 处理 GET /api/v1/studio/shots。
func (h *Shot) List(w http.ResponseWriter, r *http.Request) {
	workspaceID, ok := h.resolveWorkspace(w, r)
	if !ok {
		return
	}

	query := r.URL.Query()
	page, pageSize, msg := parsePagination(query.Get("page"), query.Get("page_size"))
	if msg != "" {
		response.WriteError(w, http.StatusUnprocessableEntity, msg)
		return
	}

	params := store.ShotListParams{
		WorkspaceID: workspaceID,
		OrderField:  query.Get("order"),
		Desc:        query.Get("is_desc") == "true",
		Page:        page,
		PageSize:    pageSize,
	}
	if v := query.Get("chapter_id"); v != "" {
		params.ChapterID = &v
	}
	if v := query.Get("q"); v != "" {
		params.Keyword = &v
	}

	items, total, err := h.shots.List(r.Context(), params)
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取镜头列表失败")
		return
	}

	out := make([]shotRead, 0, len(items))
	for _, item := range items {
		out = append(out, toShotRead(item))
	}
	response.WriteSuccess(w, newPaginated(out, page, pageSize, total))
}

// ListFrames 处理 GET /api/v1/studio/shot-frame-images。
func (h *Shot) ListFrames(w http.ResponseWriter, r *http.Request) {
	workspaceID, ok := h.resolveWorkspace(w, r)
	if !ok {
		return
	}

	query := r.URL.Query()
	page, pageSize, msg := parsePagination(query.Get("page"), query.Get("page_size"))
	if msg != "" {
		response.WriteError(w, http.StatusUnprocessableEntity, msg)
		return
	}

	params := store.FrameImageListParams{
		WorkspaceID: workspaceID,
		OrderField:  query.Get("order"),
		Desc:        query.Get("is_desc") == "true",
		Page:        page,
		PageSize:    pageSize,
	}
	if v := query.Get("shot_detail_id"); v != "" {
		params.ShotDetailID = &v
	}

	items, total, err := h.frames.List(r.Context(), params)
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取帧图列表失败")
		return
	}

	out := make([]frameImageRead, 0, len(items))
	for _, item := range items {
		out = append(out, frameImageRead{
			ID:           item.ID,
			ShotDetailID: item.ShotDetailID,
			FrameType:    item.FrameType,
			FileID:       item.FileID,
			Width:        item.Width,
			Height:       item.Height,
			Format:       item.Format,
		})
	}
	response.WriteSuccess(w, newPaginated(out, page, pageSize, total))
}

// GetDetail 处理 GET /api/v1/studio/shot-details/{shot_id}。
func (h *Shot) GetDetail(w http.ResponseWriter, r *http.Request) {
	workspaceID, ok := h.resolveWorkspace(w, r)
	if !ok {
		return
	}

	item, err := h.details.Get(r.Context(), chi.URLParam(r, "shot_id"), workspaceID)
	if errors.Is(err, store.ErrNotFound) {
		response.WriteError(w, http.StatusNotFound, "ShotDetail not found")
		return
	}
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取镜头细节失败")
		return
	}

	response.WriteSuccess(w, shotDetailRead{
		ID:                 item.ID,
		CameraShot:         item.CameraShot,
		Angle:              item.Angle,
		Movement:           item.Movement,
		SceneID:            item.SceneID,
		Duration:           item.Duration,
		OverrideVideoRatio: item.OverrideVideoRatio,
		MoodTags:           item.MoodTags,
		Atmosphere:         item.Atmosphere,
		FollowAtmosphere:   item.FollowAtmosphere,
		HasBGM:             item.HasBGM,
		VFXType:            item.VFXType,
		VFXNote:            item.VFXNote,
		ActionBeats:        item.ActionBeats,
		FirstFramePrompt:   item.FirstFramePrompt,
		LastFramePrompt:    item.LastFramePrompt,
		KeyFramePrompt:     item.KeyFramePrompt,
	})
}

// resolveWorkspace 解析当前请求所属工作区。
func (h *Shot) resolveWorkspace(w http.ResponseWriter, r *http.Request) (string, bool) {
	userID, ok := middleware.UserIDFromContext(r.Context())
	if !ok {
		response.WriteError(w, http.StatusUnauthorized, "未登录，请先登录")
		return "", false
	}
	workspaceID, _, err := h.workspaces.Resolve(r.Context(), userID, r.Header.Get("X-Workspace-ID"))
	if errors.Is(err, store.ErrNotFound) {
		response.WriteError(w, http.StatusNotFound, "工作区不存在")
		return "", false
	}
	if err != nil {
		response.WriteError(w, http.StatusInternalServerError, "读取工作区失败")
		return "", false
	}
	return workspaceID, true
}

// toShotRead 把 store 结构转成响应结构。
func toShotRead(s *store.ShotRow) shotRead {
	state := s.ExtractionState()
	var lastExtracted *string
	if s.LastExtractedAt != nil {
		// 与 Python 的 datetime.isoformat() 一致：无时区后缀、尾随零省略。
		v := s.LastExtractedAt.Format("2006-01-02T15:04:05.999999")
		lastExtracted = &v
	}
	return shotRead{
		ID:                   s.ID,
		ChapterID:            s.ChapterID,
		Index:                s.Index,
		Title:                s.Title,
		Thumbnail:            s.Thumbnail,
		Status:               s.Status,
		SkipExtraction:       s.SkipExtraction,
		ScriptExcerpt:        s.ScriptExcerpt,
		GeneratedVideoFileID: s.GeneratedVideoFileID,
		GeneratedAudioFileID: s.GeneratedAudioFileID,
		LastExtractedAt:      lastExtracted,
		Extraction: extractionSummaryRead{
			State:                  state,
			HasExtracted:           s.LastExtractedAt != nil,
			LastExtractedAt:        lastExtracted,
			AssetCandidateTotal:    s.AssetCandidateTotal,
			DialogueCandidateTotal: s.DialogueCandidateTotal,
			PendingAssetCount:      s.PendingAssetCount,
			PendingDialogueCount:   s.PendingDialogueCount,
		},
	}
}
