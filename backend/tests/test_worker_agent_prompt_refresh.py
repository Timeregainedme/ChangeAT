"""Worker 任务执行入口的 Agent 提示词刷新测试。

验证 `AbstractWorkerTaskExecutor._execute_phase` 在执行任务前会调用
`refresh_published_agent_prompts_sync`（模板页发布后跨进程生效的关键入口）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base
from app.models.task import GenerationTask
from app.services.worker.task_executor import AbstractWorkerTaskExecutor, WorkerTaskContext


class _MinimalExecutor(AbstractWorkerTaskExecutor):
    """只实现 execute 的最小执行器：记录被调用，返回固定结果。"""

    task_kind = "test_refresh"

    def __init__(self, *, session_maker) -> None:  # noqa: ANN001
        super().__init__(session_maker=session_maker)
        self.executed: list[tuple[WorkerTaskContext, dict[str, Any]]] = []

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> dict[str, str]:
        self.executed.append((ctx, run_args))
        return {"status": "ok"}


def _build_executor(tmp_path):
    from pathlib import Path

    db_path = Path(tmp_path) / "worker-refresh.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    session_local = sessionmaker(engine, class_=Session, expire_on_commit=False)

    import app.models.task  # noqa: F401

    Base.metadata.create_all(engine)
    with session_local() as db:
        db.add(
            GenerationTask(
                id="task-1",
                mode="async_polling",
                task_kind="test_refresh",
                status="pending",
                progress=0,
                payload={"task_kind": "test_refresh", "run_args": {"chapter_id": "chapter-1"}},
                result=None,
                error="",
            )
        )
        db.commit()

    return _MinimalExecutor(session_maker=session_local), session_local, engine


def test_execute_phase_refreshes_agent_prompts_before_task(tmp_path, monkeypatch) -> None:
    """任务执行前调用 refresh，且传入的是当前 db 会话。"""
    executor, session_local, engine = _build_executor(tmp_path)

    calls: list[tuple[str, object]] = []

    def _spy(db: Session, *, force: bool = False) -> None:
        calls.append(("refresh", db))

    monkeypatch.setattr(
        "app.chains.agents.prompt_registry.refresh_published_agent_prompts_sync",
        _spy,
    )

    executor._execute_phase("task-1", {"chapter_id": "chapter-1"})

    assert len(calls) == 1
    refresh_name, refresh_db = calls[0]
    assert refresh_name == "refresh"
    assert isinstance(refresh_db, Session)
    assert len(executor.executed) == 1
    assert executor.executed[0][1]["chapter_id"] == "chapter-1"

    engine.dispose()


def test_execute_phase_refresh_failure_does_not_block_task(tmp_path, monkeypatch) -> None:
    """刷新失败不阻断任务：提示词保持旧缓存/代码默认，任务照常执行。"""
    executor, session_local, engine = _build_executor(tmp_path)

    def _exploding(db: Session, *, force: bool = False) -> None:
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        "app.chains.agents.prompt_registry.refresh_published_agent_prompts_sync",
        _exploding,
    )

    result = executor._execute_phase("task-1", {"chapter_id": "chapter-1"})

    assert result == {"status": "ok"}
    assert len(executor.executed) == 1
    engine.dispose()
