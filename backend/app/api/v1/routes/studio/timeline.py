"""时间线 / 成片导出路由。

时间线是聚合视图（按章节顺序把镜头串起来），导出则调用 ffmpeg 把各镜头的
已生成视频拼成一个成片文件。两者都挂在 `/api/v1/studio/timeline` 下。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.common import ApiResponse, success_response
from app.schemas.studio.timeline import ProjectTimelineRead, TimelineExportRead
from app.services.studio.timeline import export_project_timeline, get_project_timeline

router = APIRouter()


@router.get(
    "/projects/{project_id}",
    response_model=ApiResponse[ProjectTimelineRead],
    summary="项目时间线（按章节顺序聚合的分镜片段）",
)
async def get_project_timeline_api(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProjectTimelineRead]:
    return success_response(await get_project_timeline(db, project_id=project_id))


@router.post(
    "/projects/{project_id}/export",
    response_model=ApiResponse[TimelineExportRead],
    summary="导出成片（ffmpeg 拼接全部镜头视频）",
)
async def export_project_timeline_api(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TimelineExportRead]:
    result = await export_project_timeline(db, project_id=project_id)
    await db.commit()
    return success_response(result)
