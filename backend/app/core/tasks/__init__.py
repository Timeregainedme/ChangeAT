"""Tasks for the skills runtime."""

from app.core.tasks.image_generation_tasks import ImageGenerationTask
from app.core.contracts.image_generation import ImageGenerationInput, ImageGenerationResult
from app.core.contracts.audio_generation import AudioGenerationInput, AudioGenerationResult
from app.core.contracts.provider import ProviderConfig, ProviderKey
from app.core.tasks.audio_generation_tasks import AudioGenerationTask
from app.core.tasks.video_generation_tasks import VideoGenerationTask
from app.core.contracts.video_generation import VideoGenerationInput, VideoGenerationResult

__all__ = [
    "ProviderConfig",
    "ProviderKey",
    "VideoGenerationInput",
    "VideoGenerationResult",
    "VideoGenerationTask",
    "ImageGenerationInput",
    "ImageGenerationResult",
    "ImageGenerationTask",
    "AudioGenerationInput",
    "AudioGenerationResult",
    "AudioGenerationTask",
]
