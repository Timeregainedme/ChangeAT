"""Worker 任务执行入口的 Agent 提示词刷新测试。

覆盖两条真实路径（评审 B-4 / C-6）：
1. `AbstractWorkerTaskExecutor._execute_phase`（同步执行器走基类 run）；
2. `AbstractAsyncDelegatingExecutor.run` —— 图片/视频/音频生成任务走的异步桥，
   它**不复用**基类 `run()` / `_execute_phase()`，因此必须自己刷新；
3. `refresh_published_agent_prompts_sync` 的真实 DB 分支（TTL、无已发布行、
   已发布但内容为空），不再用 monkeypatch 替身把生产路径替换掉。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models.task  # noqa: F401
from app.chains.agents import prompt_registry
from app.chains.agents.prompt_registry import (
    get_agent_prompt,
    refresh_published_agent_prompts_sync,
)
from app.core.db import Base
from app.models.studio import PromptTemplate
from app.models.task import GenerationTask
from app.models.types import PromptCategory
from app.services.worker.task_executor import (
    AbstractAsyncDelegatingExecutor,
    AbstractWorkerTaskExecutor,
    WorkerTaskContext,
)


class _MinimalExecutor(AbstractWorkerTaskExecutor):
    """只实现 execute 的最小执行器：记录被调用，返回固定结果。"""

    task_kind = "test_refresh"

    def __init__(self, *, session_maker) -> None:  # noqa: ANN001
        super().__init__(session_maker=session_maker)
        self.executed: list[tuple[WorkerTaskContext, dict[str, Any]]] = []

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> dict[str, str]:
        self.executed.append((ctx, run_args))
        return {"status": "ok"}


class _CountingSession(Session):
    """记录 UPDATE/SELECT 语句条数的 Session，用于断言 TTL 真的跳过了查库。

    只统计「刷新查询」那条 SELECT（`FROM prompt_templates`），避免把任务本身
    的读写算进来。
    """

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.prompt_selects = 0

    def execute(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        text = str(statement)
        if "FROM prompt_templates" in text and "published_at IS NOT NULL" in text:
            self.prompt_selects += 1
        return super().execute(statement, *args, **kwargs)


@pytest.fixture(autouse=True)
def _reset_registry_state() -> None:
    """隔离注册表的进程内状态（缓存 / 首刷标记 / 刷新计时）。"""
    prompt_registry._cache.clear()
    prompt_registry._loaded_once = False
    prompt_registry._last_refresh_monotonic = 0.0
    yield
    prompt_registry._cache.clear()
    prompt_registry._loaded_once = False
    prompt_registry._last_refresh_monotonic = 0.0


@pytest.fixture()
def session_local(tmp_path) -> sessionmaker[Session]:
    """建一个真实 sqlite 文件库，含 GenerationTask 与 prompt_templates 表。"""
    from pathlib import Path

    db_path = Path(tmp_path) / "worker-refresh.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, class_=Session, expire_on_commit=False)
    yield maker
    engine.dispose()


def _seed_task(maker: sessionmaker[Session], *, task_id: str = "task-1") -> None:
    with maker() as db:
        db.add(
            GenerationTask(
                workspace_id="ws-test",
                id=task_id,
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


def _seed_template(
    maker: sessionmaker[Session],
    *,
    template_id: str = "tpl-1",
    category: PromptCategory = PromptCategory.agent_script_division,
    content: str = "已发布提示词",
    published: bool = True,
) -> None:
    now = datetime.now(UTC)
    with maker() as db:
        db.add(
            PromptTemplate(
                id=template_id,
                category=category,
                name="测试模板",
                preview="",
                content=content,
                variables=[],
                is_default=False,
                is_system=False,
                published_at=now if published else None,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


def _build_executor(tmp_path):
    """兼容旧用例签名的同步执行器构造器。"""
    from pathlib import Path

    db_path = Path(tmp_path) / "worker-refresh.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    session_local = sessionmaker(engine, class_=Session, expire_on_commit=False)

    import app.models.task  # noqa: F401

    Base.metadata.create_all(engine)
    with session_local() as db:
        db.add(
            GenerationTask(
                workspace_id="ws-test",
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


# ---------- B-4：异步桥（图片/视频/音频生成）也必须刷新 ----------


class _RunnerRecorder:
    """模拟 async runner：把「运行时刻的注册表缓存」记录成证据。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def __call__(self, task_id: str, run_args: dict[str, Any]) -> None:
        self.calls.append((task_id, run_args, dict(prompt_registry._cache)))


def _build_async_executor(maker: sessionmaker[Session], runner) -> AbstractAsyncDelegatingExecutor:  # noqa: ANN001
    return AbstractAsyncDelegatingExecutor(
        task_kind="test_async_refresh",
        runner=runner,
        timeout_seconds=30.0,
        session_maker=maker,
    )


def test_async_delegating_executor_refreshes_before_runner(session_local, monkeypatch) -> None:
    """关键回归（B-4）：异步桥 run() 必须先把已发布模板刷进本进程缓存。

    旧实现下 `h3_video` 等任务永远读不到用户在模板页「发布生效」的内容，
    因为 `AbstractAsyncDelegatingExecutor.run` 覆盖了基类 run 且不调 `_execute_phase`。
    """
    _seed_task(session_local)
    _seed_template(session_local, content="用户新发布的提示词")

    probes: list[dict[str, str]] = []
    reloads: list[int] = []
    real_refresh = prompt_registry.refresh_published_agent_prompts_sync
    real_reload = prompt_registry._reload_from_rows

    def _probe_reload(rows) -> None:  # noqa: ANN001
        reloads.append(len(rows))
        real_reload(rows)

    def _probe(db: Session, *, force: bool = False) -> None:
        real_refresh(db)
        probes.append(dict(prompt_registry._cache))

    monkeypatch.setattr(
        "app.chains.agents.prompt_registry.refresh_published_agent_prompts_sync",
        _probe,
    )
    monkeypatch.setattr(
        "app.chains.agents.prompt_registry._reload_from_rows",
        _probe_reload,
    )

    runner = _RunnerRecorder()
    executor = _build_async_executor(session_local, runner)
    executor.run("task-1")

    # 刷新确实发生在任务入口，并真的查库重建了缓存
    assert len(probes) == 1
    assert probes[0]["script_division"] == "用户新发布的提示词"
    assert reloads == [1]  # 查库一次、取回一行
    # runner 实际读到的就是新发布内容
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "task-1"
    assert runner.calls[0][1]["chapter_id"] == "chapter-1"
    assert runner.calls[0][2]["script_division"] == "用户新发布的提示词"

    # 第二次任务在 TTL 内：刷新入口仍被调用，但不再查库（未发生 reload）
    executor.run("task-1")
    assert reloads == [1]
    assert len(runner.calls) == 2
    assert runner.calls[1][2]["script_division"] == "用户新发布的提示词"


def test_async_delegating_executor_continues_when_refresh_fails(session_local, monkeypatch) -> None:
    """异步桥刷新失败不阻断任务（沿用旧缓存 / 代码默认）。"""
    _seed_task(session_local)

    def _exploding(db: Session, *, force: bool = False) -> None:
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        "app.chains.agents.prompt_registry.refresh_published_agent_prompts_sync",
        _exploding,
    )

    runner = _RunnerRecorder()
    executor = _build_async_executor(session_local, runner)
    executor.run("task-1")

    assert len(runner.calls) == 1


# ---------- C-6：生产实际走的 sync 刷新分支 ----------


def test_sync_refresh_loads_published_row_from_real_db(tmp_path) -> None:
    """真实 DB 分支：已发布行被加载进缓存，第二次调用被 TTL 跳过。"""
    from pathlib import Path

    from sqlalchemy import text

    db_path = Path(tmp_path) / "counting.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, class_=_CountingSession, expire_on_commit=False)

    _seed_template(maker, content="真实库里的已发布内容")
    _seed_template(
        maker,
        template_id="tpl-draft",
        category=PromptCategory.agent_h3_video,
        content="未发布草稿",
        published=False,
    )

    with maker() as db:
        refresh_published_agent_prompts_sync(db)
        assert get_agent_prompt("script_division") == "真实库里的已发布内容"
        assert get_agent_prompt("h3_video") is None  # 未发布不进缓存
        assert db.prompt_selects == 1

        # TTL 内再次调用：跳过查库
        refresh_published_agent_prompts_sync(db)
        assert db.prompt_selects == 1

        # 对照：绕过注册表 TTL 直接查库时计数会增长（证明计数器有效）
        db.execute(text("SELECT id FROM prompt_templates WHERE published_at IS NOT NULL"))
        assert db.prompt_selects == 2

    engine.dispose()


def test_sync_refresh_with_no_published_rows_keeps_ttl(tmp_path) -> None:
    """无已发布行（全部「恢复默认」）：缓存为空但 TTL 仍然生效（评审 C-4）。"""
    from pathlib import Path

    from sqlalchemy import text

    db_path = Path(tmp_path) / "counting-empty.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, class_=_CountingSession, expire_on_commit=False)

    _seed_template(maker, content="未发布", published=False)

    with maker() as db:
        refresh_published_agent_prompts_sync(db)
        assert prompt_registry._cache == {}
        assert db.prompt_selects == 1

        # 旧实现用 `not _cache` 当首刷判据，这里会变成 2（每个任务入口都查库）
        refresh_published_agent_prompts_sync(db)
        assert db.prompt_selects == 1
        assert get_agent_prompt("script_division") is None

        db.execute(text("SELECT id FROM prompt_templates WHERE published_at IS NOT NULL"))
        assert db.prompt_selects == 2  # 计数器有效

    engine.dispose()


def test_sync_refresh_loads_published_row_with_empty_content(session_local) -> None:
    """已发布但内容为空：刷新不报错，并忠实地把空内容放进缓存。

    这是 C-6 要求的行为用例：写入侧（publish / update）已拒绝空内容，
    读取侧不额外吞掉该行 —— 否则「已发布」与「未发布」在运行时不可区分。
    """
    _seed_template(session_local, content="", published=True)

    with session_local() as db:
        refresh_published_agent_prompts_sync(db)

    assert prompt_registry._cache == {"script_division": ""}
    assert get_agent_prompt("script_division") == ""
