"""文件列表的租户隔离回归测试。

补的是一个**实际存在的越权**：`GET /api/v1/studio/files` 在不带 `project_id` 时
走 `list_files_paginated`，而它没有任何 workspace 过滤 —— 任何登录账号都能列出
全公司所有素材（含其他工作区的生成产物）。生产访问日志里确实存在这种不带
`project_id` 的调用。

另外 `list_files_by_scope_paginated` 虽然按 project_id 过滤，但 project_id 来自
query 参数、没有 router 级守卫，传别家 project_id 就能列出对方全部文件。

`files` 表自身没有归属列（一个文件可被多项目复用），因此判定用 EXISTS 语义：
**任一条 file_usages 记录指向当前工作区的项目即放行**。
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import FileItem, FileUsage, Project
from app.models.types import FileUsageKind, ProjectStyle, ProjectVisualStyle
from app.services.studio import files as files_service
from app.services.studio.file_usages import list_files_by_scope_paginated


async def _build_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


def _project(pid: str, workspace_id: str) -> Project:
    return Project(
        id=pid,
        workspace_id=workspace_id,
        name=f"项目-{pid}",
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
        seed=0,
        unify_style=True,
        progress=0,
        use_dialog_audio_as_reference=True,
        stats={},
    )


def _file(fid: str, name: str) -> FileItem:
    return FileItem(
        id=fid,
        type="image",
        name=name,
        thumbnail="",
        tags=[],
        storage_key=f"files/{fid}.png",
    )


async def _scenario() -> None:
    maker, engine = await _build_session()
    try:
        async with maker() as db:
            db.add_all([
                _project("proj-ws1", "ws-1"),
                _project("proj-ws2", "ws-2"),
                _file("file-ws1", "ws1 的图"),
                _file("file-ws2", "ws2 的图"),
                FileUsage(file_id="file-ws1", project_id="proj-ws1", usage_kind=FileUsageKind.upload),
                FileUsage(file_id="file-ws2", project_id="proj-ws2", usage_kind=FileUsageKind.upload),
            ])
            await db.commit()

            # 1) 不带 project_id 的列表必须按工作区过滤
            resp = await files_service.list_files_paginated(
                db,
                q=None,
                order=None,
                is_desc=False,
                page=1,
                page_size=10,
                workspace_id="ws-1",
            )
            payload = json.loads(resp.model_dump_json())
            ids = [item["id"] for item in payload["data"]["items"]]
            assert ids == ["file-ws1"], f"ws-1 看到了别家文件: {ids}"
            assert payload["data"]["pagination"]["total"] == 1

            # 2) 传别家 project_id 也不能列出对方文件
            items, total = await list_files_by_scope_paginated(
                db,
                project_id="proj-ws2",
                workspace_id="ws-1",
            )
            assert items == [], f"跨租户 project_id 不应返回数据: {[i.id for i in items]}"
            assert total == 0

            # 3) 自己的 project_id 正常
            items2, total2 = await list_files_by_scope_paginated(
                db,
                project_id="proj-ws1",
                workspace_id="ws-1",
            )
            assert [i.id for i in items2] == ["file-ws1"]
            assert total2 == 1
    finally:
        await engine.dispose()


def test_file_list_is_workspace_scoped() -> None:
    """文件列表在「无 project_id」与「跨租户 project_id」两种形态下都必须隔离。"""
    asyncio.run(_scenario())
