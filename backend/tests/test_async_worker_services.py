from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import DeliveryMode
from app.models.studio import (
    CameraAngle,
    CameraMovement,
    CameraShotType,
    Chapter,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Shot,
    ShotDetail,
    VFXType,
)
from app.models.task import GenerationTask, GenerationTaskStatus
from app.services.film.generated_video import run_video_generation_task
from app.services.film.shot_frame_prompt_tasks import run_shot_frame_prompt_task
from app.services.studio.image_task_runner import run_image_generation_task


@pytest.mark.asyncio
async def test_run_video_generation_task_marks_cancelled_before_execute(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "video-worker-cancel.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import app.models.task  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as db:
        store = SqlAlchemyTaskStore(db)
        task = await store.create(
            payload={"task_kind": "video_generation", "run_args": {"shot_id": "shot-1"}},
            mode=DeliveryMode.async_polling,
            task_kind="video_generation",
        )
        await store.request_cancel(task.id, "用户取消")
        await db.commit()

    monkeypatch.setattr("app.services.film.generated_video.async_session_maker", session_local)

    await run_video_generation_task(task_id=task.id, run_args={"shot_id": "shot-1"})

    async with session_local() as db:
        row = await db.get(GenerationTask, task.id)
        assert row is not None
        assert row.status == GenerationTaskStatus.cancelled
        assert bool(row.cancel_requested) is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_image_generation_task_marks_cancelled_before_execute(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "image-worker-cancel.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import app.models.task  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as db:
        store = SqlAlchemyTaskStore(db)
        task = await store.create(
            payload={
                "task_kind": "image_generation",
                "run_args": {"relation_type": "character", "relation_entity_id": "char-1"},
            },
            mode=DeliveryMode.async_polling,
            task_kind="image_generation",
        )
        await store.request_cancel(task.id, "用户取消")
        await db.commit()

    monkeypatch.setattr("app.services.studio.image_task_runner.async_session_maker", session_local)

    await run_image_generation_task(
        task_id=task.id,
        run_args={"relation_type": "character", "relation_entity_id": "char-1"},
    )

    async with session_local() as db:
        row = await db.get(GenerationTask, task.id)
        assert row is not None
        assert row.status == GenerationTaskStatus.cancelled
        assert bool(row.cancel_requested) is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_shot_frame_prompt_task_marks_cancelled_before_execute(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "shot-frame-worker-cancel.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import app.models.task  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as db:
        store = SqlAlchemyTaskStore(db)
        task = await store.create(
            payload={"task_kind": "shot_frame_prompt", "run_args": {"shot_id": "shot-1", "frame_type": "first"}},
            mode=DeliveryMode.async_polling,
            task_kind="shot_frame_prompt",
        )
        await store.request_cancel(task.id, "用户取消")
        await db.commit()

    monkeypatch.setattr("app.services.film.shot_frame_prompt_tasks.async_session_maker", session_local)

    await run_shot_frame_prompt_task(task_id=task.id, run_args={"shot_id": "shot-1", "frame_type": "first"})

    async with session_local() as db:
        row = await db.get(GenerationTask, task.id)
        assert row is not None
        assert row.status == GenerationTaskStatus.cancelled
        assert bool(row.cancel_requested) is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_shot_frame_prompt_task_persists_debug_context(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "shot-frame-worker-success.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import app.models.task  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as db:
        db.add_all(
            [
                Project(
                    id="project-1",
                    name="项目一",
                    description="",
                    style=ProjectStyle.real_people_city,
                    visual_style=ProjectVisualStyle.live_action,
                ),
                Chapter(id="chapter-1", project_id="project-1", index=1, title="第一章"),
                Shot(id="shot-1", chapter_id="chapter-1", index=1, title="镜头一", script_excerpt="主角回头。"),
                ShotDetail(
                    id="shot-1",
                    camera_shot=CameraShotType.ms,
                    angle=CameraAngle.eye_level,
                    movement=CameraMovement.static,
                    duration=3,
                    atmosphere="紧张",
                    mood_tags=["紧张"],
                    vfx_type=VFXType.none,
                    vfx_note="无",
                ),
            ]
        )
        store = SqlAlchemyTaskStore(db)
        task = await store.create(
            payload={
                "task_kind": "shot_frame_prompt",
                "run_args": {
                    "shot_id": "shot-1",
                    "frame_type": "first",
                    "input": {"script_excerpt": "主角回头。", "visual_style": "现实"},
                },
            },
            mode=DeliveryMode.async_polling,
            task_kind="shot_frame_prompt",
        )
        await db.commit()

    class _FakeAgent:
        def __init__(self, _llm, **_kwargs) -> None:
            pass

        async def aextract(self, **_kwargs):
            return type("Result", (), {"prompt": "中景，主角警惕地回头。", "model_dump": lambda self: {"prompt": "中景，主角警惕地回头。"}})()

    monkeypatch.setattr("app.services.film.shot_frame_prompt_tasks.async_session_maker", session_local)
    monkeypatch.setattr("app.services.film.shot_frame_prompt_tasks.build_default_text_llm_sync", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("app.services.film.shot_frame_prompt_tasks.ShotFirstFramePromptAgent", _FakeAgent)

    await run_shot_frame_prompt_task(
        task_id=task.id,
        run_args={
            "shot_id": "shot-1",
            "frame_type": "first",
            "input": {"script_excerpt": "主角回头。", "visual_style": "现实", "character_context": "- 主角：警惕"},
        },
    )

    async with session_local() as db:
        row = await db.get(GenerationTask, task.id)
        detail = await db.get(ShotDetail, "shot-1")
        assert row is not None
        assert row.status == GenerationTaskStatus.succeeded
        assert isinstance(row.result, dict)
        assert row.result["prompt"] == "中景，主角警惕地回头。"
        assert row.result["debug_context"]["visual_style"] == "现实"
        assert row.result["debug_context"]["character_context"] == "- 主角：警惕"
        assert row.result["quality_checks"]["passed"] is True
        assert row.result["quality_checks"]["issues"] == []
        assert detail is not None
        assert detail.first_frame_prompt == "中景，主角警惕地回头。"

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_shot_frame_prompt_task_retries_when_result_contains_mapping_text(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "shot-frame-worker-retry.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import app.models.task  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as db:
        db.add_all(
            [
                Project(
                    id="project-1",
                    name="项目一",
                    description="",
                    style=ProjectStyle.real_people_city,
                    visual_style=ProjectVisualStyle.live_action,
                ),
                Chapter(id="chapter-1", project_id="project-1", index=1, title="第一章"),
                Shot(id="shot-1", chapter_id="chapter-1", index=1, title="镜头一", script_excerpt="主角回头。"),
                ShotDetail(
                    id="shot-1",
                    camera_shot=CameraShotType.ms,
                    angle=CameraAngle.eye_level,
                    movement=CameraMovement.static,
                    duration=3,
                    atmosphere="紧张",
                    mood_tags=["紧张"],
                    vfx_type=VFXType.none,
                    vfx_note="无",
                ),
            ]
        )
        store = SqlAlchemyTaskStore(db)
        task = await store.create(
            payload={
                "task_kind": "shot_frame_prompt",
                "run_args": {
                    "shot_id": "shot-1",
                    "frame_type": "first",
                    "input": {"script_excerpt": "主角回头。", "character_context": "- 主角：警惕"},
                },
            },
            mode=DeliveryMode.async_polling,
            task_kind="shot_frame_prompt",
        )
        await db.commit()

    class _FakeAgent:
        calls: list[dict] = []

        def __init__(self, _llm, **_kwargs) -> None:
            pass

        async def aextract(self, **kwargs):
            _FakeAgent.calls.append(dict(kwargs))
            if len(_FakeAgent.calls) == 1:
                return type(
                    "Result",
                    (),
                    {
                        "prompt": "## 图片内容说明\n图1: 主角\n## 生成内容\n图1警惕地回头。",
                        "model_dump": lambda self: {"prompt": self.prompt},
                    },
                )()
            return type(
                "Result",
                (),
                {
                    "prompt": "中景，主角警惕地回头。",
                    "model_dump": lambda self: {"prompt": self.prompt},
                },
            )()

    monkeypatch.setattr("app.services.film.shot_frame_prompt_tasks.async_session_maker", session_local)
    monkeypatch.setattr("app.services.film.shot_frame_prompt_tasks.build_default_text_llm_sync", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("app.services.film.shot_frame_prompt_tasks.ShotFirstFramePromptAgent", _FakeAgent)

    await run_shot_frame_prompt_task(
        task_id=task.id,
        run_args={
            "shot_id": "shot-1",
            "frame_type": "first",
            "input": {"script_excerpt": "主角回头。", "character_context": "- 主角：警惕"},
        },
    )

    async with session_local() as db:
        row = await db.get(GenerationTask, task.id)
        detail = await db.get(ShotDetail, "shot-1")
        assert row is not None
        assert row.status == GenerationTaskStatus.succeeded
        assert isinstance(row.result, dict)
        assert row.result["prompt"] == "中景，主角警惕地回头。"
        assert row.result["debug_context"]["retry_guidance"]
        assert row.result["quality_checks"]["passed"] is True
        assert row.result["quality_checks"]["issues"] == []
        assert detail is not None
        assert detail.first_frame_prompt == "中景，主角警惕地回头。"

    assert len(_FakeAgent.calls) == 2
    assert _FakeAgent.calls[1]["retry_guidance"]

    await engine.dispose()
