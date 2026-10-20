"""Studio 实体缩略图解析。

设计说明（重要）：
- 素材文件存在对象存储（当前为 Cloudflare R2），`files.thumbnail` 列保存的是
  **可直接访问的公开 URL**。
- 早期实现统一返回 `/api/v1/studio/files/{id}/download` 这个后端代理路径，
  但 `studio` 路由整体挂了 `require_auth`，导致浏览器 `<img src>` 无法携带
  Authorization 头 → 401 → 前端图片全部裂图。
- 因此这里优先使用 `files.thumbnail`（公开 URL）；只有当其为空（例如换了私有桶
  且未配置公开域名）时才回退到受鉴权的下载代理路径。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import AssetViewAngle, FileItem

DOWNLOAD_URL_TEMPLATE = "/api/v1/studio/files/{file_id}/download"


def download_url(file_id: str) -> str:
    """受鉴权的下载代理路径（fallback 用）。"""
    return DOWNLOAD_URL_TEMPLATE.format(file_id=file_id)


async def _public_urls(db: AsyncSession, file_ids: list[str]) -> dict[str, str]:
    """批量取文件的可直接访问 URL（files.thumbnail）。

    返回 {file_id: url}；未命中或 URL 为空的不出现在结果中，由调用方回退。
    """
    if not file_ids:
        return {}
    uniq = list({fid for fid in file_ids if fid})
    if not uniq:
        return {}
    stmt = select(FileItem.id, FileItem.thumbnail).where(FileItem.id.in_(uniq))
    rows = (await db.execute(stmt)).all()
    return {fid: url for fid, url in rows if url}


async def resolve_thumbnails(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_ids: list[str],
) -> dict[str, str]:
    """解析每个 parent 的最佳缩略图 URL（优先公开 URL）。"""
    if not parent_ids:
        return {}

    parent_field = getattr(image_model, parent_field_name)
    stmt = select(image_model).where(parent_field.in_(parent_ids), image_model.file_id.is_not(None))
    rows = (await db.execute(stmt)).scalars().all()

    # 选出每个 parent 的最佳 file_id（front 视角优先，然后取最新）
    best: dict[str, tuple[int, int, int, str]] = {}
    for row in rows:
        file_id = row.file_id
        if not file_id:
            continue
        parent_id = getattr(row, parent_field_name)
        created_ts = int(row.created_at.timestamp()) if row.created_at else -1
        score = (1 if row.view_angle == AssetViewAngle.front else 0, created_ts, row.id)
        current = best.get(parent_id)
        if current is None or score > current[:3]:
            best[parent_id] = (*score, file_id)

    if not best:
        return {}

    # 批量换取公开 URL，缺失的回退到受鉴权代理路径
    urls = await _public_urls(db, [info[3] for info in best.values()])
    return {
        parent_id: urls.get(info[3]) or download_url(info[3])
        for parent_id, info in best.items()
    }


async def resolve_thumbnail_infos(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """解析每个 parent 的最佳缩略图信息（thumbnail + image_id）。"""
    if not parent_ids:
        return {}

    parent_field = getattr(image_model, parent_field_name)
    stmt = select(image_model).where(parent_field.in_(parent_ids), image_model.file_id.is_not(None))
    rows = (await db.execute(stmt)).scalars().all()

    best: dict[str, tuple[int, int, int, int, str]] = {}
    for row in rows:
        file_id = row.file_id
        if not file_id:
            continue
        parent_id = getattr(row, parent_field_name)
        created_ts = int(row.created_at.timestamp()) if row.created_at else -1
        image_id = int(row.id)
        score3 = (1 if row.view_angle == AssetViewAngle.front else 0, created_ts, image_id)
        current = best.get(parent_id)
        if current is None or score3 > current[:3]:
            best[parent_id] = (*score3, image_id, file_id)

    if not best:
        return {}

    urls = await _public_urls(db, [info[4] for info in best.values()])
    return {
        parent_id: {
            "image_id": info[3],
            "file_id": info[4],
            "thumbnail": urls.get(info[4]) or download_url(info[4]),
        }
        for parent_id, info in best.items()
    }
