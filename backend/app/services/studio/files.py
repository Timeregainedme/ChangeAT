"""文件服务：封装文件上传、下载、列表、详情、更新与删除。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.utils import apply_keyword_filter, apply_order, paginate
from app.core import storage
from app.models.studio import FileItem, FileType
from app.schemas.common import ApiResponse, PaginatedData, paginated_response
from app.schemas.studio import FileDetailRead, FileRead, FileUpdate, FileUsageRead, FileUsageWrite
from app.services.common import create_and_refresh, entity_not_found, flush_and_refresh, get_or_404, patch_model
from app.services.studio.file_usages import upsert_file_usage

FILE_ORDER_FIELDS = {"name", "created_at", "updated_at"}


def _detect_file_type(filename: str) -> FileType:
    _, ext = os.path.splitext(filename.lower())
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return FileType.image
    if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
        return FileType.video
    raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext or '未知后缀'}")


def _build_display_name(filename: str, name: str | None) -> str:
    if name:
        return name
    base, _ = os.path.splitext(filename)
    return base or filename


def _resolve_download_media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
    }
    if ext in media_types:
        return media_types[ext]
    if ext in {".mkv", ".avi", ".webm"}:
        return f"video/{ext.lstrip('.')}"
    return "application/octet-stream"


async def list_files_paginated(
    db: AsyncSession,
    *,
    q: str | None,
    order: str | None,
    is_desc: bool,
    page: int,
    page_size: int,
) -> ApiResponse[PaginatedData[FileRead]]:
    """分页查询文件。"""
    stmt = select(FileItem)
    stmt = apply_keyword_filter(stmt, q=q, fields=[FileItem.name])
    stmt = apply_order(
        stmt,
        model=FileItem,
        order=order,
        is_desc=is_desc,
        allow_fields=FILE_ORDER_FIELDS,
        default="created_at",
    )
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)
    return paginated_response(
        [FileRead.model_validate(x) for x in items],
        page=page,
        page_size=page_size,
        total=total,
    )


async def get_file_detail(
    db: AsyncSession,
    *,
    file_id: str,
) -> FileDetailRead:
    """获取文件详情。"""
    stmt = select(FileItem).options(selectinload(FileItem.usages)).where(FileItem.id == file_id)
    res = await db.execute(stmt)
    obj = res.scalars().first()
    if obj is None:
        raise HTTPException(status_code=404, detail=entity_not_found("File"))
    usages = [FileUsageRead.model_validate(u) for u in (obj.usages or [])]
    base = FileRead.model_validate(obj)
    return FileDetailRead(**base.model_dump(), usages=usages)


async def update_file_meta(
    db: AsyncSession,
    *,
    file_id: str,
    body: FileUpdate,
) -> FileItem:
    """更新文件元信息，并按需写入 usage。"""
    obj = await get_or_404(db, FileItem, file_id, detail=entity_not_found("File"))
    data = body.model_dump(exclude_unset=True)
    usage_payload = data.pop("usage", None)
    patch_model(obj, data)
    if usage_payload is not None:
        u = FileUsageWrite.model_validate(usage_payload)
        await upsert_file_usage(
            db,
            file_id=file_id,
            project_id=u.project_id,
            chapter_id=u.chapter_id,
            shot_id=u.shot_id,
            usage_kind=u.usage_kind,
            source_ref=u.source_ref,
        )
    return await flush_and_refresh(db, obj)


async def upload_file(
    db: AsyncSession,
    *,
    file: UploadFile,
    name: str | None = None,
    project_id: str | None = None,
    chapter_id: str | None = None,
    shot_id: str | None = None,
    usage_kind: str | None = None,
    source_ref: str | None = None,
) -> FileItem:
    """上传文件到对象存储，并创建 FileItem 记录。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="上传文件缺少文件名")

    file_type = _detect_file_type(file.filename)
    display_name = _build_display_name(file.filename, name)
    content = await file.read()

    key = f"files/{file.filename}"
    info = await storage.upload_file(
        key=key,
        data=content,
        content_type=file.content_type,
        extra_args={"ACL": "public-read"},
    )

    file_item = await create_and_refresh(
        db,
        FileItem(
            id=str(uuid.uuid4()),
            type=file_type,
            name=display_name,
            thumbnail=info.url,
            tags=[],
            storage_key=key,
        ),
    )

    if project_id and usage_kind:
        await upsert_file_usage(
            db,
            file_id=file_item.id,
            project_id=project_id,
            chapter_id=chapter_id,
            shot_id=shot_id,
            usage_kind=usage_kind,
            source_ref=source_ref,
        )

    return file_item


def _build_download_filename(file_item: FileItem) -> str:
    """下载文件名：优先用 files.name；缺后缀时补上存储对象的后缀。

    存储对象的 basename 是随机 key（如 ``937235bd-....mp4``），直接拿去下载会得到
    不可读的文件名，所以这里回落到业务侧写入的 ``name``。
    """
    storage_name = Path(file_item.storage_key).name or "download"
    suffix = Path(storage_name).suffix
    display = (file_item.name or "").strip() or storage_name
    if suffix and not display.lower().endswith(suffix.lower()):
        display = f"{display}{suffix}"
    return display


def _parse_byte_range(range_header: str | None, total: int) -> tuple[int, int] | None:
    """解析单段 HTTP Range，返回闭区间 ``(start, end)``；``None`` 表示按整文件返回。

    - 不支持多段 Range（含逗号）与非法语法：一律忽略 Range，退化为整文件返回
      （RFC 9110 允许服务端忽略 Range）。
    - ``start`` 越界：抛 416，并带上 ``Content-Range: bytes */total``。
    """
    if not range_header:
        return None
    value = range_header.strip()
    if not value.lower().startswith("bytes="):
        return None
    spec = value[len("bytes=") :].strip()
    if "," in spec:
        return None
    first, _, last = spec.partition("-")
    first, last = first.strip(), last.strip()
    if not first and not last:
        return None
    if not first:
        # 后缀区间 bytes=-N：取最后 N 字节
        if not last.isdigit():
            return None
        length = int(last)
        if length <= 0:
            return None
        return (max(0, total - length), total - 1)
    if not first.isdigit():
        return None
    start = int(first)
    if start >= total:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            detail=f"Requested range not satisfiable: start={start}, size={total}",
            headers={"Content-Range": f"bytes */{total}"},
        )
    end = total - 1
    if last:
        if not last.isdigit():
            return None
        end = min(int(last), total - 1)
    if end < start:
        return None
    return (start, end)


async def build_download_response(
    db: AsyncSession,
    *,
    file_id: str,
    range_header: str | None = None,
) -> Response:
    """根据 file_id 构建下载响应，支持单段 HTTP ``Range``（206）。

    浏览器 ``<video>`` 拖拽进度条依赖 206 响应；此前恒返回 200 全量，
    导致播放器无法 seek。
    """
    file_item = await get_or_404(db, FileItem, file_id, detail=entity_not_found("File"))

    # 对象存储已配置公开访问时，直接重定向，避免后端代理整段二进制。
    #
    # 收益（在跨洋链路上尤其明显）：
    #   - EC2 不再占用出网带宽转发视频/大图
    #   - Range 请求交给对象存储（R2/OSS 均支持），<video> seek 正常
    #   - 可被 CDN 缓存
    # 仅在 thumbnail 不是绝对 URL（私有桶 / 未配公开域名）时回退到流式代理。
    public_url = (file_item.thumbnail or "").strip()
    if public_url.startswith(("http://", "https://")):
        return RedirectResponse(url=public_url, status_code=status.HTTP_302_FOUND)

    filename = _build_download_filename(file_item)
    media_type = _resolve_download_media_type(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Accept-Ranges": "bytes",
    }

    async def _full_response() -> StreamingResponse:
        content = await storage.download_file(key=file_item.storage_key)
        headers["Content-Length"] = str(len(content))
        return StreamingResponse(iter([content]), media_type=media_type, headers=headers)

    # 无 Range：直接取全量，不额外 HEAD。
    if range_header is None:
        return await _full_response()

    info = await storage.get_file_info(key=file_item.storage_key)
    total = info.size or 0
    if total <= 0:
        return await _full_response()

    byte_range = _parse_byte_range(range_header, total)
    if byte_range is None:
        return await _full_response()

    start, end = byte_range
    content = await storage.download_file(
        key=file_item.storage_key, byte_range=(start, end)
    )
    headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    headers["Content-Length"] = str(len(content))
    return StreamingResponse(
        iter([content]),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )


async def get_storage_info(
    db: AsyncSession,
    *,
    file_id: str,
) -> dict[str, Any]:
    """读取对象存储信息。"""
    file_item = await get_or_404(db, FileItem, file_id, detail=entity_not_found("File"))
    info = await storage.get_file_info(key=file_item.storage_key)
    return {
        "key": info.key,
        "url": info.url,
        "size": info.size,
        "content_type": info.content_type,
        "etag": info.etag,
    }


async def delete_file(
    db: AsyncSession,
    *,
    file_id: str,
) -> None:
    """删除文件记录与对象存储中的内容；若记录不存在则静默返回。"""
    file_item = await db.get(FileItem, file_id)
    if file_item is None:
        return

    try:
        await storage.delete_file(key=file_item.storage_key)
    except Exception:
        # 存储删除失败不阻塞记录删除，保持当前接口语义。
        pass

    await db.delete(file_item)
    await db.flush()
