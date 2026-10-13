"""视频生成准备服务。"""

from app.services.studio.generation.video.build_base import VideoBaseDraft, build_video_base_draft
from app.services.studio.generation.video.build_context import (
    REFERENCE_MODE,
    REQUIRED_FRAMES_BY_MODE,
    VideoGenerationContext,
    build_video_context,
    required_image_count,
    resolve_video_reference_images,
    validate_images_count,
)
from app.services.studio.generation.video.build_submission import build_video_submission_payload
from app.services.studio.generation.video.derive_preview import (
    VideoDerivedPreview,
    derive_video_preview,
    resolve_reference_mode_file_ids,
)

__all__ = [
    "REFERENCE_MODE",
    "REQUIRED_FRAMES_BY_MODE",
    "VideoBaseDraft",
    "VideoDerivedPreview",
    "VideoGenerationContext",
    "build_video_base_draft",
    "build_video_context",
    "build_video_submission_payload",
    "derive_video_preview",
    "required_image_count",
    "resolve_reference_mode_file_ids",
    "resolve_video_reference_images",
    "validate_images_count",
]

