from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Mapping, Optional

from app.core.task_manager.stores import TaskStore
from app.core.task_manager.strategies import DeliveryStrategy
from app.core.task_manager.types import BaseTask, DeliveryMode, TaskRecord, TaskStatusView


class TaskManager:
    """任务管理器：对上层（路由/业务）提供统一入口。

    init params:
    - store: TaskStore, 任务存储

    特性：
    - store 可插拔：内存 or MySQL（通过 SQLAlchemy）
    - delivery strategy 可插拔：streaming / async_polling / ...（后续扩展只需新增策略并注册）
    - 为高频轮询提供轻量查询：get_status()
    """

    def __init__(self, *, store: TaskStore, strategies: Mapping[DeliveryMode, DeliveryStrategy]) -> None:
        self.store = store
        self._strategies = dict(strategies)

    def _strategy_for(self, mode: DeliveryMode) -> DeliveryStrategy:
        strategy = self._strategies.get(mode)
        if strategy is None:
            raise ValueError(f"No delivery strategy registered for mode={mode!r}")
        return strategy

    async def create(
        self,
        *,
        task: BaseTask,
        mode: DeliveryMode,
        task_kind: str | None = None,
        run_args: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> TaskRecord:
        """创建任务记录。

        参数：
        - task: 实际要执行的 Task 对象，必须实现 run/status/is_done/get_result
        - mode: 结果交付方式（流式 / 任务+轮询）
        - run_args: 传给 task.run 的参数（会序列化到 payload，便于后续 worker 使用）
        - workspace_id: 任务所属工作区。必传（或在 run_args 里带上），
          否则任务无法被租户隔离。同时写入 payload，让 worker 侧
          （`run_args["workspace_id"]`）在产出文件时能继承同一归属。
        """
        run_args = dict(run_args or {})
        resolved_workspace_id = workspace_id or run_args.get("workspace_id")
        if resolved_workspace_id:
            # 双写：payload 供 worker 读取，列供 SQL 过滤。
            run_args.setdefault("workspace_id", resolved_workspace_id)
        payload: dict[str, Any] = {
            "task_class": task.__class__.__name__,
            "task_kind": task_kind or task.__class__.__name__,
            "run_args": run_args,
        }
        return await self.store.create(
            payload=payload,
            mode=mode,
            task_kind=str(payload["task_kind"]),
            workspace_id=resolved_workspace_id,
        )

    async def start(self, *, task_id: str) -> Optional[AsyncIterator[Any]]:
        task = await self.store.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        strategy = self._strategy_for(task.mode)
        return await strategy.start(task)

    async def get_status(self, *, task_id: str) -> TaskStatusView:
        view = await self.store.get_status_view(task_id)
        if view is None:
            raise ValueError(f"Task not found: {task_id}")
        return view

    async def request_cancel(self, *, task_id: str, reason: str | None = None) -> TaskRecord:
        rec = await self.store.request_cancel(task_id, reason)
        if rec is None:
            raise ValueError(f"Task not found: {task_id}")
        return rec

    async def is_cancel_requested(self, *, task_id: str) -> bool:
        return await self.store.is_cancel_requested(task_id)

    async def mark_cancelled(self, *, task_id: str) -> TaskRecord:
        rec = await self.store.mark_cancelled(task_id)
        if rec is None:
            raise ValueError(f"Task not found: {task_id}")
        return rec

    async def stream(self, *, task_id: str) -> AsyncIterator[Any]:
        task = await self.store.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        strategy = self._strategy_for(task.mode)
        return await strategy.stream(task)
