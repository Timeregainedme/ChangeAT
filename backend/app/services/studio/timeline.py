"""项目时间线聚合与成片导出。

设计要点：

- **聚合不落表**：镜头本身已经是「按章节顺序排列的片段」。时间线视图按
  `chapter.index` → `shot.index` 排序，用 `ShotDetail.duration` 累加出 `start`/`end`，
  不新建 `timeline_clips` 行，避免与镜头表产生第二份真相。
- **导出是显式动作**：只有全部片段都有已生成的视频时才允许导出；缺片段直接报
  可读的中文错误，而不是产出一个缺头少尾的残片。
- **归一化再拼接**：不同分镜的视频可能来自不同分辨率/是否带音轨的模型产出，
  直接 `-c copy` 拼接会在流结构不一致时失败。因此先逐段转成统一的
  「固定画幅 + 恒定帧率 + 必有音轨」的中间片，再用 concat 无重编码拼起来。
- ffmpeg 需要装在**后端容器**里（`deploy/docker/backend.Dockerfile` 的 apt 依赖）。
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.models.studio import (
    Chapter,
    FileItem,
    FileType,
    Project,
    Shot,
    ShotDetail,
    ShotDialogLine,
    ShotFrameImage,
)
from app.schemas.studio.timeline import (
    ProjectTimelineRead,
    TimelineClipRead,
    TimelineDialogRead,
    TimelineExportRead,
    TimelineFrameRead,
    TimelineStatsRead,
)
from app.services.common import create_and_refresh, entity_not_found
from app.services.studio.shot_dialogs import load_character_display_names, pick_display_name

# 成片目标画幅：按项目默认视频比例取接近的偶数尺寸，未知比例回落 16:9。
_EXPORT_TARGET_SIZE: dict[str, tuple[int, int]] = {
    "9:16": (720, 1280),
    "16:9": (1280, 720),
    "1:1": (1024, 1024),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "21:9": (1680, 720),
    "3:2": (1152, 768),
    "2:3": (768, 1152),
}
_DEFAULT_EXPORT_SIZE = (1280, 720)
_ANULLSRC = "anullsrc=channel_layout=stereo:sample_rate=44100"


def _enum_text(value: object) -> str:
    """DB 里取出的枚举列是普通 str，也可能是 Enum，统一转成文本。"""
    return str(getattr(value, "value", value) or "")


def _export_size(ratio: str | None) -> tuple[int, int]:
    key = (ratio or "").strip()
    return _EXPORT_TARGET_SIZE.get(key, _DEFAULT_EXPORT_SIZE)


def _dialog_speaker_name(
    name_map: Mapping[str, str],
    line: ShotDialogLine,
) -> str | None:
    """时间轴字幕显示名：与对白列表/准备页走同一口径（角色真名优先，回落行内名字）。

    参数：
        name_map：角色 ID → 角色当前真名映射，由 :func:`load_character_display_names` 批量查询。
        line：台词行 ORM 对象。

    返回：
        显示名；沿用时间轴原有契约，空值统一归一为 ``None``（``TimelineDialogRead.speaker_name``
        是可空字段，字幕生成按「无说话人」处理）。
    """
    resolved = pick_display_name(
        name_map,
        character_id=line.speaker_character_id,
        fallback_name=line.speaker_name,
    )
    return (resolved or "").strip() or None


def _ffmpeg_binary(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise ValueError(
            f"服务器未安装 {name}，无法导出成片；请在后端镜像里安装 ffmpeg 后重试"
        )
    return found


async def _run_ffmpeg(args: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        _ffmpeg_binary("ffmpeg"),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        lines = stderr.decode("utf-8", "ignore").strip().splitlines()
        tail = " | ".join(line for line in lines[-8:] if line.strip())
        raise ValueError(f"ffmpeg 处理失败（exit={proc.returncode}）：{tail}")


async def _has_audio_stream(path: Path) -> bool:
    proc = await asyncio.create_subprocess_exec(
        _ffmpeg_binary("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return bool(stdout.strip())


async def _normalize_clip(src: Path, dst: Path, *, size: tuple[int, int]) -> None:
    """把一段分镜视频转成统一规格，保证可被 concat 无重编码拼接。"""
    width, height = size
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    )
    codec_args = [
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
    ]
    if await _has_audio_stream(src):
        mapping = ["-map", "0:v:0", "-map", "0:a:0"]
        inputs = ["-i", str(src)]
    else:
        # 没有音轨时补一条静音轨，否则拼接时各段流结构不一致会失败。
        inputs = ["-i", str(src), "-f", "lavfi", "-i", _ANULLSRC]
        mapping = ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    await _run_ffmpeg(["-y", *inputs, *mapping, *codec_args, str(dst)])


async def get_project_timeline(db: AsyncSession, *, project_id: str) -> ProjectTimelineRead:
    """聚合出项目时间线视图（只读，不修改任何状态）。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise ValueError(entity_not_found("Project"))

    chapters = (
        (
            await db.execute(
                select(Chapter)
                .where(Chapter.project_id == project_id)
                .order_by(Chapter.index.asc(), Chapter.id.asc())
            )
        )
        .scalars()
        .all()
    )

    chapter_meta: dict[str, tuple[int, str]] = {
        chapter.id: (int(chapter.index or 0), chapter.title or "") for chapter in chapters
    }

    shots: list[Shot] = []
    if chapter_meta:
        shots = list(
            (
                await db.execute(
                    select(Shot).where(Shot.chapter_id.in_(list(chapter_meta)))
                )
            )
            .scalars()
            .all()
        )
    shots.sort(key=lambda item: (chapter_meta.get(item.chapter_id, (0, ""))[0], item.index, item.id))

    shot_ids = [shot.id for shot in shots]
    details: dict[str, ShotDetail] = {}
    frames: dict[str, list[ShotFrameImage]] = {}
    dialogs: dict[str, list[ShotDialogLine]] = {}
    if shot_ids:
        details = {
            detail.id: detail
            for detail in (
                await db.execute(select(ShotDetail).where(ShotDetail.id.in_(shot_ids)))
            )
            .scalars()
            .all()
        }
        for frame in (
            await db.execute(
                select(ShotFrameImage)
                .where(ShotFrameImage.shot_detail_id.in_(shot_ids))
                .order_by(ShotFrameImage.id.asc())
            )
        ).scalars().all():
            frames.setdefault(frame.shot_detail_id, []).append(frame)
        for line in (
            await db.execute(
                select(ShotDialogLine)
                .where(ShotDialogLine.shot_detail_id.in_(shot_ids))
                .order_by(
                    ShotDialogLine.shot_detail_id.asc(),
                    ShotDialogLine.index.asc(),
                    ShotDialogLine.id.asc(),
                )
            )
        ).scalars().all():
            dialogs.setdefault(line.shot_detail_id, []).append(line)

    # 字幕显示名统一口径：能解析到角色就显示角色真名，解析不到才回落行内名字（C-2）。
    dialog_name_map = await load_character_display_names(
        db,
        character_ids=[
            character_id
            for lines in dialogs.values()
            for line in lines
            for character_id in (line.speaker_character_id, line.target_character_id)
        ],
    )

    clips: list[TimelineClipRead] = []
    cursor = 0.0
    for shot in shots:
        detail = details.get(shot.id)
        duration = int(detail.duration or 0) if detail is not None else 0
        chapter_index, chapter_title = chapter_meta.get(shot.chapter_id, (0, ""))
        start = cursor
        cursor += float(duration)
        video_file_id = str(shot.generated_video_file_id or "").strip() or None
        audio_file_id = str(shot.generated_audio_file_id or "").strip() or None
        clips.append(
            TimelineClipRead(
                shot_id=shot.id,
                chapter_id=shot.chapter_id,
                chapter_index=chapter_index,
                chapter_title=chapter_title,
                index=int(shot.index or 0),
                title=shot.title or "",
                status=_enum_text(shot.status),
                duration=duration,
                start=start,
                end=cursor,
                video_file_id=video_file_id,
                audio_file_id=audio_file_id,
                thumbnail=shot.thumbnail or "",
                frames=[
                    TimelineFrameRead(
                        frame_type=_enum_text(frame.frame_type),
                        file_id=str(frame.file_id or "").strip() or None,
                        width=frame.width,
                        height=frame.height,
                        format=frame.format or "png",
                    )
                    for frame in frames.get(shot.id, [])
                ],
                dialogs=[
                    TimelineDialogRead(
                        line_id=line.id,
                        index=int(line.index or 0),
                        text=line.text or "",
                        emotion=(line.emotion or "").strip() or None,
                        speaker_name=_dialog_speaker_name(dialog_name_map, line),
                        audio_file_id=str(line.generated_audio_file_id or "").strip() or None,
                    )
                    for line in dialogs.get(shot.id, [])
                ],
            )
        )

    clips_with_video = sum(1 for clip in clips if clip.video_file_id)
    clips_with_audio = sum(
        1
        for clip in clips
        if clip.audio_file_id or any(dialog.audio_file_id for dialog in clip.dialogs)
    )
    stats = TimelineStatsRead(
        clip_count=len(clips),
        total_duration=cursor,
        clips_with_video=clips_with_video,
        clips_missing_video=len(clips) - clips_with_video,
        clips_with_audio=clips_with_audio,
        exportable=bool(clips) and clips_with_video == len(clips),
    )
    return ProjectTimelineRead(
        project_id=project.id,
        project_name=project.name or "",
        video_ratio=(project.default_video_ratio or "").strip() or None,
        clips=clips,
        stats=stats,
    )


async def export_project_timeline(db: AsyncSession, *, project_id: str) -> TimelineExportRead:
    """把项目下全部镜头按时间线顺序拼成一个成片文件。"""
    timeline = await get_project_timeline(db, project_id=project_id)
    if not timeline.clips:
        raise ValueError("该项目还没有分镜，无法导出成片")

    missing = [clip for clip in timeline.clips if not clip.video_file_id]
    if missing:
        titles = "、".join(f"第{clip.index}镜「{clip.title}」" for clip in missing[:5])
        suffix = "" if len(missing) <= 5 else f" 等 {len(missing)} 个"
        raise ValueError(f"还有 {len(missing)} 个分镜没有生成视频，无法导出成片：{titles}{suffix}")

    file_ids = [clip.video_file_id for clip in timeline.clips if clip.video_file_id]
    rows = (
        (await db.execute(select(FileItem).where(FileItem.id.in_(file_ids)))).scalars().all()
    )
    files_by_id = {item.id: item for item in rows}

    size = _export_size(timeline.video_ratio)
    workdir = Path(tempfile.mkdtemp(prefix="jellyfish-export-"))
    try:
        normalized: list[Path] = []
        for position, clip in enumerate(timeline.clips, start=1):
            item = files_by_id.get(clip.video_file_id or "")
            if item is None:
                raise ValueError(f"分镜「{clip.title}」的视频文件记录已不存在，无法导出")
            payload = await storage.download_file(key=item.storage_key)
            source = workdir / f"src-{position:03d}.mp4"
            source.write_bytes(payload)
            target = workdir / f"norm-{position:03d}.mp4"
            await _normalize_clip(source, target, size=size)
            normalized.append(target)

        concat_list = workdir / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{path.name}'" for path in normalized) + "\n",
            encoding="utf-8",
        )
        output = workdir / "output.mp4"
        await _run_ffmpeg(
            [
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        result = output.read_bytes()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    key = f"exports/{project_id}/{uuid.uuid4()}.mp4"
    stored = await storage.upload_file(
        key=key,
        data=result,
        content_type="video/mp4",
        extra_args={"ACL": "public-read"},
    )
    name = f"{timeline.project_name or project_id}-成片.mp4"
    file_item = await create_and_refresh(
        db,
        FileItem(
            id=str(uuid.uuid4()),
            type=FileType.video,
            name=name,
            # 写入对象存储返回的公开 URL。
            # 之前这里硬编码空字符串，导致成片无法直接用 CDN 地址访问，
            # 只能回退到后端代理下载（占用 EC2 出网带宽，且 HEAD 请求会失败）。
            thumbnail=stored.url,
            tags=["export"],
            storage_key=key,
        ),
    )
    return TimelineExportRead(
        file_id=file_item.id,
        name=file_item.name,
        storage_key=file_item.storage_key,
        download_path=f"/api/v1/studio/files/{file_item.id}/download",
        clip_count=len(timeline.clips),
        duration=timeline.stats.total_duration,
    )
