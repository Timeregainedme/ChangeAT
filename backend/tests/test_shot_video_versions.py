"""镜头视频版本（抽卡历史）服务测试。

覆盖两件事：版本列表能正确还原每次抽卡的提示词/画幅/时长并标记当前版本；
「采用」只切换指针、绝不销毁历史版本。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import (
    Chapter,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Shot,
)
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.task_links import GenerationTaskLink, GenerationTaskLinkStatus
from app.services.studio.shot_video_versions import (
    adopt_shot_video_version,
    list_shot_video_versions,
)


async def _build_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


async def _seed_shot(db: AsyncSession, *, shot_id: str = "s1", current: str | None = None) -> Shot:
    """确保项目/章节存在后插入镜头；可对同一会话重复调用（多个镜头共用 p1/c1）。"""
    if await db.get(Project, "p1") is None:
        db.add(
            Project(
                workspace_id="ws-test",
                id="p1",
                name="项目一",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            )
        )
        db.add(Chapter(id="c1", project_id="p1", index=1, title="第一章"))
        await db.flush()
    shot = Shot(
        id=shot_id,
        chapter_id="c1",
        index=1 if shot_id == "s1" else 2,
        title="镜头一",
        script_excerpt="林晚推开窗。",
        generated_video_file_id=current,
    )
    db.add(shot)
    await db.flush()
    return shot


def _video_payload(*, prompt: str, ratio: str = "9:16", seconds: int = 5) -> dict:
    return {
        "task_kind": "video_generation",
        "run_args": {
            "input": {
                "model": "minimax-h3",
                "prompt": prompt,
                "ratio": ratio,
                "seconds": seconds,
                "reference_images": [],
            },
            "provider": "minimax",
        },
    }


async def _add_version(
    db: AsyncSession,
    *,
    task_id: str,
    shot_id: str = "s1",
    file_id: str | None = "f1",
    created_at: datetime,
    status: GenerationTaskStatus = GenerationTaskStatus.succeeded,
    error: str = "",
    payload: dict | None = None,
    task_kind: str = "video_generation",
    relation_type: str = "video",
    resource_type: str = "video",
) -> None:
    task = GenerationTask(
        workspace_id="ws-test",
        id=task_id,
        mode=GenerationDeliveryMode.async_polling,
        task_kind=task_kind,
        status=status,
        payload=payload if payload is not None else _video_payload(prompt=f"提示词-{task_id}"),
        error=error,
        created_at=created_at,
        updated_at=created_at,
    )
    link = GenerationTaskLink(
        task_id=task_id,
        resource_type=resource_type,
        relation_type=relation_type,
        relation_entity_id=shot_id,
        file_id=file_id,
        status=GenerationTaskLinkStatus.accepted,
    )
    db.add_all([task, link])
    await db.flush()


@pytest.mark.asyncio
async def test_list_versions_orders_desc_and_marks_current() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_shot(db, current="f_old")
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await _add_version(db, task_id="t_old", file_id="f_old", created_at=base)
        await _add_version(db, task_id="t_new", file_id="f_new", created_at=base + timedelta(minutes=5))

        versions = await list_shot_video_versions(db, shot_id="s1")

        assert [item.task_id for item in versions] == ["t_new", "t_old"]
        assert [item.is_current for item in versions] == [False, True]
        assert all(item.file_id for item in versions)
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_versions_restores_prompt_ratio_and_seconds() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_shot(db, current="f1")
        await _add_version(
            db,
            task_id="t1",
            file_id="f1",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            payload=_video_payload(prompt="林晚推开窗，晨光打在脸上", ratio="9:16", seconds=5),
        )

        versions = await list_shot_video_versions(db, shot_id="s1")

        assert len(versions) == 1
        assert versions[0].prompt == "林晚推开窗，晨光打在脸上"
        assert versions[0].ratio == "9:16"
        assert versions[0].seconds == 5.0
        assert versions[0].status == "succeeded"
        assert versions[0].error is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_versions_falls_back_to_prompt_preview_and_keeps_error() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_shot(db)
        await _add_version(
            db,
            task_id="t_failed",
            file_id=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status=GenerationTaskStatus.failed,
            error="provider timeout",
            payload={"run_args": {"prompt_preview": {"prompt": "预览里的提示词"}}},
        )

        versions = await list_shot_video_versions(db, shot_id="s1")

        assert versions[0].prompt == "预览里的提示词"
        assert versions[0].file_id is None
        assert versions[0].is_current is False
        assert versions[0].ratio is None
        assert versions[0].seconds is None
        assert versions[0].status == "failed"
        assert versions[0].error == "provider timeout"
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_versions_ignores_other_shots_and_other_task_kinds() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_shot(db)
        await _seed_shot(db, shot_id="s2")
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await _add_version(db, task_id="t_ok", file_id="f1", created_at=base)
        await _add_version(db, task_id="t_other_shot", shot_id="s2", file_id="f2", created_at=base)
        await _add_version(
            db,
            task_id="t_audio",
            file_id="a1",
            created_at=base,
            task_kind="audio_generation",
            resource_type="audio",
        )

        versions = await list_shot_video_versions(db, shot_id="s1")

        assert [item.task_id for item in versions] == ["t_ok"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_versions_unknown_shot_raises_value_error() -> None:
    db, engine = await _build_session()
    async with db:
        with pytest.raises(ValueError):
            await list_shot_video_versions(db, shot_id="missing")
    await engine.dispose()


@pytest.mark.asyncio
async def test_adopt_switches_pointer_without_dropping_history() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_shot(db, current="f_new")
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await _add_version(db, task_id="t_old", file_id="f_old", created_at=base)
        await _add_version(db, task_id="t_new", file_id="f_new", created_at=base + timedelta(minutes=5))

        shot = await adopt_shot_video_version(db, shot_id="s1", file_id="f_old")

        assert shot.generated_video_file_id == "f_old"
        versions = await list_shot_video_versions(db, shot_id="s1")
        assert [item.task_id for item in versions] == ["t_new", "t_old"]
        assert [item.is_current for item in versions] == [False, True]
    await engine.dispose()


@pytest.mark.asyncio
async def test_adopt_rejects_file_from_another_shot() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_shot(db)
        await _seed_shot(db, shot_id="s2")
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await _add_version(db, task_id="t1", file_id="f1", created_at=base)
        await _add_version(db, task_id="t2", shot_id="s2", file_id="f2", created_at=base)

        with pytest.raises(ValueError, match="not a generated video version of this shot"):
            await adopt_shot_video_version(db, shot_id="s1", file_id="f2")
    await engine.dispose()


@pytest.mark.asyncio
async def test_adopt_rejects_blank_file_id() -> None:
    db, engine = await _build_session()
    async with db:
        await _seed_shot(db)
        with pytest.raises(ValueError, match="file_id is required"):
            await adopt_shot_video_version(db, shot_id="s1", file_id="   ")
    await engine.dispose()


@pytest.mark.asyncio
async def test_adopt_unknown_shot_raises_value_error() -> None:
    db, engine = await _build_session()
    async with db:
        with pytest.raises(ValueError):
            await adopt_shot_video_version(db, shot_id="missing", file_id="f1")
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_versions_handles_large_inline_payload() -> None:
    """回归：payload 内含内联 base64 参考图（线上实测单行约 11 MB）。

    本用例在 SQLite 上只验证「大 payload 下版本列表仍能正确排序并还原元信息」。
    真正的线上故障是 MySQL 排序缓冲（``sort_buffer_size=256KB``）对宽行排序直接报
    ``(1038, 'Out of sort memory, consider increasing server sort buffer size')``，
    所以 ``list_shot_video_versions`` 的排序必须走 ``(link_id, task_id)`` 窄列，
    绝不能 ``select(GenerationTaskLink, GenerationTask)`` 后对整行排序——
    否则任何含大 payload 的项目在这一页就会 500。
    """
    db, engine = await _build_session()
    async with db:
        await _seed_shot(db, current="f_big")
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        huge = "data:image/png;base64," + "A" * (2 * 1024 * 1024)
        payload = {
            "run_args": {
                "input": {
                    "model": "gpt-image-2.5-flare",
                    "prompt": "含参考图的一版",
                    "ratio": "16:9",
                    "seconds": 4,
                    "images": [{"image_url": huge}],
                }
            }
        }
        await _add_version(db, task_id="t_small", file_id="f_small", created_at=base)
        await _add_version(
            db,
            task_id="t_big",
            file_id="f_big",
            created_at=base + timedelta(minutes=5),
            payload=payload,
        )

        versions = await list_shot_video_versions(db, shot_id="s1")

        assert [item.task_id for item in versions] == ["t_big", "t_small"]
        assert versions[0].is_current is True
        assert versions[0].prompt == "含参考图的一版"
        assert versions[0].ratio == "16:9"
        assert versions[0].seconds == 4.0
    await engine.dispose()
