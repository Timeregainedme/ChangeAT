from __future__ import annotations

"""文件相关工具：从 URL 或 base64 内容创建 FileItem，并上传到对象存储。"""

import asyncio
import base64
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.models.studio import FileItem, FileType
from app.models.types import FileUsageKind

logger = logging.getLogger(__name__)

# 默认下载超时与重试。
#
# 为什么需要：供应商（PIX / 优云智算等）返回的是它们自己的 CDN 直链，
# 后端要先把生成结果抓回来再上传对象存储。在 us-east-2 这类跨洋链路上，
# 抓一张 200-300KB 的图经常超过 httpx 默认的 5 秒（默认 timeout 未显式指定时
# 就是 5s），表现为 httpx.ReadTimeout，最终整个生成任务被判失败——
# 但供应商那边已经扣费出图，属于纯损失。
# 因此这里给一个明显更宽松的默认值，并对瞬时网络错误做指数退避重试。
DEFAULT_DOWNLOAD_TIMEOUT_S = 120.0
DEFAULT_DOWNLOAD_RETRIES = 3
_RETRYABLE_EXC = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.RemoteProtocolError,
    httpx.ReadError,
)


async def _infer_file_type_from_ext(ext: str) -> FileType:
    ext = ext.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return FileType.image
    if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
        return FileType.video
    if ext in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}:
        return FileType.audio
    # 默认按图片处理，调用方若有更精细需求可在外层再封装
    return FileType.image


@dataclass(frozen=True)
class FileUsageCreateParams:
    """创建 FileItem 后写入 file_usages 的参数。"""

    project_id: str
    chapter_id: str | None = None
    shot_id: str | None = None
    usage_kind: FileUsageKind | str = FileUsageKind.api
    source_ref: str | None = None


async def _infer_file_type_from_content_type(content_type: str | None) -> FileType:
    if not content_type:
        return FileType.image
    ct = content_type.lower()
    if ct.startswith("image/"):
        return FileType.image
    if ct.startswith("video/"):
        return FileType.video
    if ct.startswith("audio/"):
        return FileType.audio
    return FileType.image


async def create_file_from_url_or_b64(
    session: AsyncSession,
    *,
    url: str | None = None,
    b64_data: str | None = None,
    name: str | None = None,
    prefix: str = "files",
    url_request_headers: dict[str, str] | None = None,
    httpx_timeout: float | None = None,
    usage: FileUsageCreateParams | None = None,
) -> FileItem:
    """从远端 URL 或 base64 内容创建 FileItem。

    - 若提供 url：会先下载内容，推断 content_type 和后缀；
    - 若提供 b64_data：优先解析 data URL 前缀中的 MIME 类型，否则默认 image/png；
    - 始终通过 storage.upload_file 上传到对象存储，再创建 FileItem 记录并返回。
    - url_request_headers / httpx_timeout：用于需鉴权或大文件下载（如 OpenAI /videos/{id}/content）。
    """
    if not url and not b64_data:
        raise ValueError("create_file_from_url_or_b64 需要提供 url 或 b64_data 至少其一")

    content: bytes
    content_type: str | None = None
    filename: str = ""

    if url:
        # 超时与重试：见文件顶部常量说明。
        # 显式给定 timeout，避免落回 httpx 默认的 5 秒。
        client_kwargs: dict = {
            "timeout": httpx_timeout if httpx_timeout is not None else DEFAULT_DOWNLOAD_TIMEOUT_S,
            "follow_redirects": True,
        }
        last_exc: Exception | None = None
        async with httpx.AsyncClient(**client_kwargs) as client:
            for attempt in range(1, DEFAULT_DOWNLOAD_RETRIES + 1):
                try:
                    resp = await client.get(url, headers=url_request_headers or None)
                    resp.raise_for_status()
                    content = resp.content
                    content_type = resp.headers.get("Content-Type")
                    last_exc = None
                    break
                except _RETRYABLE_EXC as exc:
                    last_exc = exc
                    if attempt >= DEFAULT_DOWNLOAD_RETRIES:
                        break
                    backoff = 2 ** (attempt - 1)
                    logger.warning(
                        "下载素材失败（第 %s/%s 次，%s: %s），%ss 后重试: %s",
                        attempt,
                        DEFAULT_DOWNLOAD_RETRIES,
                        type(exc).__name__,
                        exc or "(无消息)",
                        backoff,
                        url,
                    )
                    await asyncio.sleep(backoff)

        if last_exc is not None:
            # 把异常类型拼进消息：httpx.ReadTimeout 的 str() 是空串，
            # 直接 raise 会让上层写入的 error 字段为空，排查时看不到原因。
            raise RuntimeError(
                f"下载素材失败（已重试 {DEFAULT_DOWNLOAD_RETRIES} 次，超时 {client_kwargs['timeout']}s）: "
                f"{type(last_exc).__name__}: {last_exc or '无错误消息'} | url={url}"
            ) from last_exc

        # 从 URL 推断文件名
        path = Path(httpx.URL(url).path)
        filename = path.name or "file"
    else:
        raw = b64_data or ""
        # 支持 data URL 形式：data:image/png;base64,xxxxxx
        if raw.startswith("data:") and ";base64," in raw:
            header, encoded = raw.split(";base64,", 1)
            # 形如 data:image/png
            mime = header[5:]
            content_type = mime or "image/png"
            content = base64.b64decode(encoded)
        else:
            content_type = "image/png"
            content = base64.b64decode(raw)

        filename = "image.png"

    # 推断扩展名和 FileType
    _, ext = os.path.splitext(filename)
    file_type = await _infer_file_type_from_content_type(content_type)
    if not ext:
        # 根据类型给一个默认后缀（音频接口目前只产出 WAV）
        ext = {FileType.image: ".png", FileType.video: ".mp4", FileType.audio: ".wav"}[file_type]
    else:
        # URL 后缀可能与真实类型不符（如签名链接无后缀），以内容类型推断结果为准
        inferred = file_type
        ext_from_name = await _infer_file_type_from_ext(ext)
        if inferred == FileType.image and ext_from_name != FileType.image:
            file_type = ext_from_name
            ext = {FileType.video: ".mp4", FileType.audio: ".wav"}.get(file_type, ext)

    display_name = name or os.path.splitext(filename)[0] or filename

    key = f"{prefix}/{uuid.uuid4().hex}{ext}"
    info = await storage.upload_file(
        key=key,
        data=content,
        content_type=content_type,
        extra_args={"ACL": "public-read"},
    )

    file_id = str(uuid.uuid4())
    file_obj = FileItem(
        id=file_id,
        type=file_type,
        name=display_name,
        thumbnail=info.url,
        tags=[],
        storage_key=key,
    )
    session.add(file_obj)
    await session.flush()
    await session.refresh(file_obj)

    if usage is not None:
        from app.services.studio.file_usages import upsert_file_usage

        await upsert_file_usage(
            session,
            file_id=file_obj.id,
            project_id=usage.project_id,
            chapter_id=usage.chapter_id,
            shot_id=usage.shot_id,
            usage_kind=usage.usage_kind,
            source_ref=usage.source_ref,
        )

    return file_obj

