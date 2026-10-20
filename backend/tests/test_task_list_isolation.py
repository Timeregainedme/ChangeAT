"""任务列表的租户隔离回归测试。

这个文件是为一个**实际存在的漏洞**补的测试：
`/api/v1/film/tasks` 是列表接口，路径里没有可被 router 级守卫拦截的资源 ID，
而 `list_task_views` 当时也没有 workspace 过滤 —— 任何登录账号都能看到
全公司所有生成任务（含其他租户的任务内容、失败原因）。

为什么之前没被发现：
router 级守卫（`require_scoped_resource`）的设计前提是「路径里有资源 ID」，
列表接口天然不满足；而隔离阶段只验证了单条 task 的 404，没验证列表。
测试用真实 DB 覆盖，避免再用替身把这条路径漏过去。
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.task_manager.stores import SqlAlchemyTaskStore
from app.models.task import GenerationTask


async def _build_session() -> tuple[AsyncSession, object]:
    """建一个带全部表的内存库。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


def _task(task_id: str, workspace_id: str) -> GenerationTask:
    return GenerationTask(
        id=task_id,
        workspace_id=workspace_id,
        mode="async_polling",
        task_kind="video_generation",
        status="succeeded",
        progress=100,
        payload={},
        result=None,
        error="",
    )


async def _scenario() -> None:
    maker, engine = await _build_session()
    try:
        async with maker() as db:
            db.add_all([
                _task("task-in-ws1", "ws-1"),
                _task("task-in-ws2", "ws-2"),
                _task("task-in-ws3", "ws-3"),
            ])
            await db.commit()

            store = SqlAlchemyTaskStore(db)

            # 关键断言：ws-1 只能看到自己的任务。
            items, total = await store.list_task_views(
                statuses=None,
                task_kind=None,
                relation_type=None,
                relation_entity_id=None,
                recent_seconds=None,
                page=1,
                page_size=20,
                workspace_id="ws-1",
            )
            ids = [item.id for item in items]
            assert ids == ["task-in-ws1"], f"ws-1 看到了别家任务: {ids}"
            assert total == 1, f"total 应只统计本工作区，实际 {total}"

            # 另一个工作区同样只能看到自己的。
            items2, total2 = await store.list_task_views(
                statuses=None,
                task_kind=None,
                relation_type=None,
                relation_entity_id=None,
                recent_seconds=None,
                page=1,
                page_size=20,
                workspace_id="ws-2",
            )
            assert [i.id for i in items2] == ["task-in-ws2"], "ws-2 隔离失效"
            assert total2 == 1

            # 不传 workspace_id 时保持旧行为（内部调用 / 运维脚本），便于排障。
            items_all, total_all = await store.list_task_views(
                statuses=None,
                task_kind=None,
                relation_type=None,
                relation_entity_id=None,
                recent_seconds=None,
                page=1,
                page_size=20,
                workspace_id=None,
            )
            assert total_all == 3, f"未指定工作区时应返回全部，实际 {total_all}"
            assert len(items_all) == 3
    finally:
        await engine.dispose()


def test_task_list_is_workspace_scoped() -> None:
    """列表必须按工作区过滤，且 total 与 items 口径一致。"""
    asyncio.run(_scenario())
