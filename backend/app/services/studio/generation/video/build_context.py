from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import ShotFrameImage, ShotFrameType
from app.services.studio.generation.shared.types import GenerationContext

REQUIRED_FRAMES_BY_MODE: dict[str, tuple[ShotFrameType, ...]] = {
    "first": (ShotFrameType.first,),
    "last": (ShotFrameType.last,),
    "key": (ShotFrameType.key,),
    "first_last": (ShotFrameType.first, ShotFrameType.last),
    "first_last_key": (ShotFrameType.first, ShotFrameType.last, ShotFrameType.key),
    "text_only": (),
    # 参考图模式：帧不参与，参考图由 IR 的有序参考列表决定（见 derive_preview）。
    "reference": (),
}

REFERENCE_MODE = "reference"
# H3 参考图上限（与 compshare_video_capabilities.H3_MAX_REFERENCE_IMAGES 保持一致）。
REFERENCE_MAX_IMAGES = 9


def required_image_count(reference_mode: str) -> int:
    return len(REQUIRED_FRAMES_BY_MODE[reference_mode])


def validate_images_count(reference_mode: str, images: list[str]) -> None:
    actual = len(images or [])
    if reference_mode == REFERENCE_MODE:
        if actual == 0:
            # 参考图来自 IR 的有序参考列表；空镜（角色已关联但剧本里没出现）会解析出 0 张。
            raise HTTPException(
                status_code=400,
                detail=(
                    "reference_mode=reference 需要至少 1 张参考图，但本镜头没有可用参考图。"
                    "角色卡只在剧本中出现该角色时才会插入；空镜请改用 text_only。"
                ),
            )
        if actual > REFERENCE_MAX_IMAGES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"reference_mode={reference_mode} 最多支持 {REFERENCE_MAX_IMAGES} 张参考图，"
                    f"当前 {actual} 张"
                ),
            )
        return
    expected = required_image_count(reference_mode)
    if actual != expected:
        raise HTTPException(
            status_code=400,
            detail=f"reference_mode={reference_mode} requires exactly {expected} images, got {actual}",
        )


async def resolve_video_reference_images(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
    images: list[str] | None = None,
) -> list[str]:
    normalized = [str(item).strip() for item in (images or []) if str(item).strip()]
    if reference_mode == REFERENCE_MODE:
        # 参考图模式不使用分镜帧；真实参考图由 IR 的有序参考列表提供。
        if normalized:
            validate_images_count(reference_mode, normalized)
        return normalized
    if normalized:
        validate_images_count(reference_mode, normalized)
        return normalized

    required_frames = REQUIRED_FRAMES_BY_MODE[reference_mode]
    if not required_frames:
        return []

    stmt = select(ShotFrameImage).where(
        ShotFrameImage.shot_detail_id == shot_id,
        ShotFrameImage.frame_type.in_(required_frames),
    )
    rows = (await db.execute(stmt)).scalars().all()
    frame_map = {row.frame_type: row for row in rows}

    missing: list[ShotFrameType] = []
    ordered_images: list[str] = []
    for frame_type in required_frames:
        row = frame_map.get(frame_type)
        if row is None or not row.file_id:
            missing.append(frame_type)
            continue
        ordered_images.append(str(row.file_id))

    if missing:
        missing_name = ",".join(item.value for item in missing)
        raise HTTPException(
            status_code=400,
            detail=f"Required frame image is missing: {missing_name}; please generate it first",
        )
    return ordered_images


class VideoGenerationContext(GenerationContext):
    """视频生成的动态上下文。"""

    kind: str = "video"
    shot_id: str
    reference_mode: str
    images: list[str]
    template_id: str | None = None
    # 目标视频供应商与模型：渲染器按它选择提示词方言（H3 走官方六段，其它走通用模板）。
    provider: str = ""
    model: str = ""
    # 生效后的视频比例（竖屏短剧通常是 9:16），用于提示词里的构图描述。
    ratio: str = ""


async def build_video_context(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
    images: list[str] | None,
    template_id: str | None = None,
    provider: str = "",
    model: str = "",
    ratio: str = "",
) -> VideoGenerationContext:
    resolved_images = await resolve_video_reference_images(
        db,
        shot_id=shot_id,
        reference_mode=reference_mode,
        images=images,
    )
    return VideoGenerationContext(
        shot_id=shot_id,
        reference_mode=reference_mode,
        images=resolved_images,
        template_id=template_id,
        provider=provider,
        model=model,
        ratio=ratio,
    )

