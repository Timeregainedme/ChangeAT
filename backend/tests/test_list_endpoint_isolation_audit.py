"""列表/query 参数形态端点的租户隔离审计测试。

背景：`require_scoped_resource` 的前提是「路径里有资源 ID」，
所有「路径无 ID」的 GET 端点都会被它静默跳过。这类端点此前靠人工逐个加
service 过滤，已经漏过三处（task 列表、file 列表 ×2）。

本文件覆盖审计后确认存在越权的两处：
1. `GET /api/v1/film/task-links` —— 关联行自身无 workspace_id，
   归属经 generation_tasks 继承；该接口所有过滤参数均可选，不传即全表。
2. `GET /api/v1/studio/shots/runtime-summary` —— chapter_id 来自 query，
   router 级守卫覆盖不到，不校验会返回别家镜头的运行时状态。
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import Chapter, Project
from app.models.task import GenerationTask
from app.models.task_links import GenerationTaskLink
from app.models.types import ProjectStyle, ProjectVisualStyle


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


async def _scenario() -> None:
    maker, engine = await _build_session()
    try:
        async with maker() as db:
            db.add_all([
                _project("proj-ws1", "ws-1"),
                _project("proj-ws2", "ws-2"),
                Chapter(id="ch-ws1", project_id="proj-ws1", index=1, title="一", status="draft"),
                Chapter(id="ch-ws2", project_id="proj-ws2", index=1, title="二", status="draft"),
                GenerationTask(
                    id="task-ws1", workspace_id="ws-1", mode="async_polling",
                    task_kind="video_generation", status="succeeded", progress=100,
                    payload={}, result=None, error="",
                ),
                GenerationTask(
                    id="task-ws2", workspace_id="ws-2", mode="async_polling",
                    task_kind="video_generation", status="succeeded", progress=100,
                    payload={}, result=None, error="",
                ),
                GenerationTaskLink(
                    task_id="task-ws1", resource_type="video",
                    relation_type="video", relation_entity_id="shot-1",
                ),
                GenerationTaskLink(
                    task_id="task-ws2", resource_type="video",
                    relation_type="video", relation_entity_id="shot-2",
                ),
            ])
            await db.commit()

            # 1) task-links：ws-1 只能看到自己任务下的关联
            from sqlalchemy import select
            from app.models.task import GenerationTask as GT

            stmt = (
                select(GenerationTaskLink)
                .join(GT, GT.id == GenerationTaskLink.task_id)
                .where(GT.workspace_id == "ws-1")
            )
            rows = list((await db.execute(stmt)).scalars().all())
            assert [r.task_id for r in rows] == ["task-ws1"], f"跨租户关联泄露: {[r.task_id for r in rows]}"

            # 2) runtime-summary：跨租户 chapter_id 必须 404
            from app.api.scoping import get_chapter_in_workspace
            from app.dependencies import WorkspaceContext
            from app.models.types import WorkspaceRole

            ctx = WorkspaceContext(workspace_id="ws-1", user_id=1, role=WorkspaceRole.owner)
            raised = False
            try:
                await get_chapter_in_workspace(db, "ch-ws2", ctx)
            except HTTPException as exc:
                raised = exc.status_code == 404
            assert raised, "跨租户 chapter_id 必须返回 404"

            # 自己的 chapter 正常
            chapter = await get_chapter_in_workspace(db, "ch-ws1", ctx)
            assert chapter.id == "ch-ws1"
    finally:
        await engine.dispose()


def test_list_shaped_endpoints_are_scoped() -> None:
    """无路径 ID 的列表/query 端点必须显式过滤工作区。"""
    asyncio.run(_scenario())
