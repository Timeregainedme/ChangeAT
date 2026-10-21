"""时间线 / 成片导出路由。

时间线是聚合视图（按章节顺序把镜头串起来），导出则调用 ffmpeg 把各镜头的
已生成视频拼成一个成片文件。两者都挂在 `/api/v1/studio/timeline` 下。
"""

from __future__ import annotations

import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.scoping import get_project_in_workspace, require_scoped_resource
from app.dependencies import get_db
from app.schemas.common import ApiResponse, success_response
from app.schemas.studio.timeline import ProjectTimelineRead, TimelineExportRead
from app.services.studio.timeline import (
    build_clips_archive,
    export_project_timeline,
    get_project_timeline,
)

router = APIRouter(
    # 时间线按项目聚合，路径里的 project_id 必须先校验工作区归属。
    dependencies=[Depends(require_scoped_resource("project_id", get_project_in_workspace))],
)


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


@router.get(
    "/projects/{project_id}/clips-archive",
    summary="打包导出全部片段视频（zip）",
    response_class=StreamingResponse,
)
async def export_project_clips_archive_api(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """把每个片段的视频原样打包下载。

    与「导出成片」互补：成片要求所有片段都有视频并串成一个 mp4；
    这里允许部分片段缺失，缺的会写进 zip 里的 MANIFEST 说明文件。
    """
    try:
        content, filename, _count = await build_clips_archive(db, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Content-Length": str(len(content)),
    }
    return StreamingResponse(io.BytesIO(content), media_type="application/zip", headers=headers)
