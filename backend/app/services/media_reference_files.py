"""参考素材的「引用存储、派发期物化」。

设计对齐 toonflow（`apps/server/src/utils/ai/requestFiles.ts` 的 `useReference` /
`offload`，以及 `apps/server/src/utils/media/generation.ts` 的 `readReference`）：

- 写进 `generation_tasks.payload` 的 `run_args` **只保存 file_id 引用**，绝不内联 base64；
- 真正需要 data URL / 字节流时，在**任务执行端、调用供应商前一刻**才从对象存储
  下载并编码。

原因：base64 参考图单张可达数 MB（线上实测一行 payload 约 11 MB）。这类大列一旦
写进 `generation_tasks.payload`，会让 MySQL 在默认 `sort_buffer_size`（256KB）下
对任何含该表的排序直接报
``(1038, 'Out of sort memory, consider increasing server sort buffer size')``，
同时撑大备份、拖慢任务中心。引用存储后 payload 保持 KB 级。
"""

from __future__ import annotations

import base64
import mimetypes

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.models.studio import FileItem

_INVALID_FILE_ID_DETAIL = "Invalid image file_id: {file_id}"


async def _image_content_type(file_obj: FileItem) -> str | None:
    """取对象存储里的 MIME；拿不到就按扩展名猜。"""
    content_type: str | None = None
    try:
        info = await storage.get_file_info(key=file_obj.storage_key)
        content_type = (info.content_type or "").strip().lower() or None
    except Exception:  # noqa: BLE001
        content_type = None
    if not content_type:
        guessed_type, _ = mimetypes.guess_type(file_obj.storage_key)
        content_type = (guessed_type or "").strip().lower() or None
    return content_type


async def assert_reference_image_file_id(db: AsyncSession, *, file_id: str) -> None:
    """校验 file_id 指向一份可用图片素材；只读元信息，不下载内容。

    写入 run_args 之前调用，保证坏引用在**提交任务时**就报 400，
    而不是等到 worker 执行时才失败。
    """
    file_obj = await db.get(FileItem, file_id)
    if file_obj is None or not file_obj.storage_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_INVALID_FILE_ID_DETAIL.format(file_id=file_id),
        )
    content_type = await _image_content_type(file_obj)
    if not content_type or not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_INVALID_FILE_ID_DETAIL.format(file_id=file_id),
        )


async def image_data_url_from_file_id(db: AsyncSession, *, file_id: str) -> str:
    """下载 file_id 对应内容并编码为 ``data:image/...;base64,...``。

    只在派发期（供应商调用前）调用。
    """
    file_obj = await db.get(FileItem, file_id)
    if file_obj is None or not file_obj.storage_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_INVALID_FILE_ID_DETAIL.format(file_id=file_id),
        )
    try:
        content = await storage.download_file(key=file_obj.storage_key)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_INVALID_FILE_ID_DETAIL.format(file_id=file_id),
        ) from None
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_INVALID_FILE_ID_DETAIL.format(file_id=file_id),
        )

    content_type = await _image_content_type(file_obj)
    if not content_type or not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_INVALID_FILE_ID_DETAIL.format(file_id=file_id),
        )
    image_format = content_type.split("/", 1)[1].split(";", 1)[0].strip().lower() or "png"
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:image/{image_format};base64,{encoded}"


async def compact_image_reference_refs(
    db: AsyncSession,
    *,
    file_ids: list[str],
) -> list[dict[str, str]]:
    """校验 file_id 列表并产出紧凑引用 ``[{"file_id": ...}]``（顺序与入参一致）。

    返回的就是将要写进 run_args 的形状：只有 id，没有字节。
    """
    refs: list[dict[str, str]] = []
    for raw in file_ids or []:
        file_id = (raw or "").strip()
        if not file_id:
            continue
        await assert_reference_image_file_id(db, file_id=file_id)
        refs.append({"file_id": file_id})
    return refs


async def materialize_image_reference_refs(
    db: AsyncSession,
    *,
    images: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    """派发期物化：``{"file_id": x}`` → ``{"image_url": "data:..."}``。

    已经带 ``image_url`` 的条目原样保留，因此**历史 payload（内联 base64）仍然可跑**。
    """
    out: list[dict[str, str]] = []
    for ref in images or []:
        if not isinstance(ref, dict):
            continue
        image_url = str(ref.get("image_url") or "").strip()
        if image_url:
            out.append({"image_url": image_url})
            continue
        file_id = str(ref.get("file_id") or "").strip()
        if not file_id:
            continue
        out.append({"image_url": await image_data_url_from_file_id(db, file_id=file_id)})
    return out


async def materialize_file_ids(db: AsyncSession, *, file_ids: list[str]) -> list[str]:
    """派发期物化：file_id 列表 → data URL 列表（顺序不变）。"""
    out: list[str] = []
    for raw in file_ids or []:
        file_id = str(raw or "").strip()
        if not file_id:
            continue
        out.append(await image_data_url_from_file_id(db, file_id=file_id))
    return out
