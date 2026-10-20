"""契约一致性单测：分镜草稿回填 / script_division 重建 / 批量资产任务响应壳。

覆盖评审：
- C-16：`build_script_extraction_draft_for_shot` 的角色草稿必须带 `voice_description`，
  否则分镜编辑页音色描述回填为空。
- C-17：`generate_extraction_result` 必须能区分「`shots` 字段缺失」与「显式空列表」，
  回退库内分镜时要有日志；重建出的行号必须满足 `ShotDivision` 的 `ge=1` 契约。
- D-12：`/studio/image-tasks/assets/batch-image-tasks` 声明 HTTP 201，业务码必须同为 201。

附带守住的既有保证：提取只产出候选与 ShotDetail 默认值，**绝不**调用分镜写库
（`write_division_result_to_chapter_sync`），因此不会覆盖用户剧本。

注意：`app/services/script_processing_worker.py` 是 **同步** 模块（用 `sqlalchemy.orm.Session`，
给 Celery worker 调用），所以相关用例用同步内存库；只有分镜草稿装配是 async。
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.studio import (
    Chapter,
    Character,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Shot,
    ShotCharacterLink,
)
from app.schemas.skills.script_processing import (
    ScriptDivisionResult,
    StudioScriptExtractionDraft,
)
from app.services.script_processing_worker import (
    _rebuild_script_division_from_shots,
    generate_extraction_result,
)
from app.services.studio.shot_extraction_draft import build_script_extraction_draft_for_shot

BATCH_ROUTE = "/api/v1/studio/image-tasks/assets/batch-image-tasks"
WORKER_LOGGER = "app.services.script_processing_worker"


def _build_sync_session() -> tuple[Session, object]:
    """建一个内存库同步会话（worker 侧写入走同步 Session，表结构由 ORM metadata 生成）。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, class_=Session, expire_on_commit=False)(), engine


async def _build_async_session() -> tuple[AsyncSession, object]:
    """建一个内存库异步会话（API/装配层用 AsyncSession）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


def _seed_project_chapter() -> list[object]:
    """公共种子：一个项目 + 一个章节。"""
    return [
        Project(
            id="p1",
            name="项目一",
            description="",
            style=ProjectStyle.real_people_city,
            visual_style=ProjectVisualStyle.live_action,
        ),
        Chapter(id="c1", project_id="p1", index=1, title="第一章"),
    ]


def test_rebuild_line_numbers_satisfy_shot_division_contract() -> None:
    """C-17：重建行号必须连续、>= 1，且整体能通过 `ScriptDivisionResult` 契约校验。"""
    db, engine = _build_sync_session()
    try:
        db.add_all(
            _seed_project_chapter()
            + [
                Shot(id="s1", chapter_id="c1", index=1, title="镜头一", script_excerpt="小雨：我回来了\n同事：这么早"),
                Shot(id="s2", chapter_id="c1", index=2, title="镜头二", script_excerpt=""),
                Shot(id="s3", chapter_id="c1", index=3, title="镜头三", script_excerpt="小雨：别问了"),
            ]
        )
        db.commit()

        rebuilt = _rebuild_script_division_from_shots(db, "c1")

        assert rebuilt["total_shots"] == 3
        # extra="forbid" 与 index/start_line/end_line 的 ge=1 会在这里真实触发
        parsed = ScriptDivisionResult.model_validate(rebuilt)
        assert [shot.index for shot in parsed.shots] == [1, 2, 3]
        assert [shot.start_line for shot in parsed.shots] == [1, 3, 4]
        assert [shot.end_line for shot in parsed.shots] == [2, 3, 4]
        assert all(shot.start_line >= 1 and shot.end_line >= shot.start_line for shot in parsed.shots)
    finally:
        db.close()
        engine.dispose()


def test_rebuild_empty_chapter_returns_empty_division() -> None:
    """C-17：章节没有分镜时返回空结构，而不是违反契约的行号占位。"""
    db, engine = _build_sync_session()
    try:
        assert _rebuild_script_division_from_shots(db, "empty-chapter") == {"shots": [], "total_shots": 0}
    finally:
        db.close()
        engine.dispose()


def _stub_extract_pipeline(monkeypatch, worker, captured: list[dict], rebuild_calls: list[str]) -> None:
    """把提取链路的 LLM/缓存/重建换成探针，并让「写分镜」直接失败。"""

    def _fake_rebuild(db, chapter_id):  # noqa: ANN001
        rebuild_calls.append(chapter_id)
        return {
            "shots": [
                {
                    "index": 1,
                    "start_line": 1,
                    "end_line": 1,
                    "script_excerpt": "库内旧摘录",
                    "shot_name": "镜头一",
                }
            ],
            "total_shots": 1,
        }

    class _FakeAgent:
        """替身 ElementExtractorAgent：只记录收到的 script_division_json。

        真实 agent 返回的是 Pydantic 草稿对象（`StudioScriptExtractionDraft`），
        服务层后续按属性访问 `result.shots` / `shot.index`；这里必须保持同一
        形态，否则会用「测试替身与生产契约不一致」掩盖真实回归。
        按输入 shots 的 index 回填，避免触发漏镜头补提取分支干扰断言。
        """

        def __init__(self, llm) -> None:  # noqa: ANN001
            self.llm = llm

        def extract(self, **kwargs):  # noqa: ANN003
            payload = json.loads(kwargs["script_division_json"])
            captured.append(payload)
            shots = [
                SimpleNamespace(index=int(shot["index"]), name="")
                for shot in payload.get("shots") or []
                if isinstance(shot, dict) and "index" in shot
            ]
            return StudioScriptExtractionDraft.model_construct(
                project_id="p1",
                chapter_id="c1",
                script_text="",
                characters=[],
                scenes=[],
                props=[],
                costumes=[],
                shots=shots,
            )

    def _forbidden_write(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("提取路径不得写库覆盖分镜（否则会覆盖用户剧本）")

    monkeypatch.setattr(worker, "_rebuild_script_division_from_shots", _fake_rebuild)
    monkeypatch.setattr(worker, "ElementExtractorAgent", _FakeAgent)
    monkeypatch.setattr(worker, "build_default_text_llm_sync", lambda db, thinking=False: None)
    monkeypatch.setattr(worker, "get_cached_script_extract", lambda key: None)
    monkeypatch.setattr(worker, "set_cached_script_extract", lambda key, result: None)
    monkeypatch.setattr(worker, "write_division_result_to_chapter_sync", _forbidden_write)


def test_extract_rebuilds_and_logs_only_when_shots_field_missing(monkeypatch, caplog) -> None:
    """C-17：`{}`（字段缺失）才回退库内分镜；日志必须说明「本次沿用了库内分镜」。"""
    import app.services.script_processing_worker as worker

    captured: list[dict] = []
    rebuild_calls: list[str] = []
    _stub_extract_pipeline(monkeypatch, worker, captured, rebuild_calls)

    with caplog.at_level(logging.INFO, logger=WORKER_LOGGER):
        generate_extraction_result(
            db=None,
            project_id="p1",
            chapter_id="c1",
            script_division={},
            consistency=None,
            refresh_cache=True,
        )

    assert rebuild_calls == ["c1"]
    assert captured[-1]["total_shots"] == 1
    assert captured[-1]["shots"][0]["script_excerpt"] == "库内旧摘录"
    assert any("沿用库内分镜" in record.getMessage() for record in caplog.records)


def test_explicit_empty_shots_does_not_fall_back_to_stored_shots(monkeypatch, caplog) -> None:
    """C-17：显式 `{"shots": []}` 是调用方意图，必须原样使用、不得静默回退库内分镜。"""
    import app.services.script_processing_worker as worker

    captured: list[dict] = []
    rebuild_calls: list[str] = []
    _stub_extract_pipeline(monkeypatch, worker, captured, rebuild_calls)

    with caplog.at_level(logging.INFO, logger=WORKER_LOGGER):
        generate_extraction_result(
            db=None,
            project_id="p1",
            chapter_id="c1",
            script_division={"shots": [], "total_shots": 0},
            consistency=None,
            refresh_cache=True,
        )

    assert rebuild_calls == []
    assert captured[-1]["shots"] == []
    assert not any("沿用库内分镜" in record.getMessage() for record in caplog.records)


async def test_extraction_draft_returns_character_voice_description() -> None:
    """C-16：分镜草稿里的角色必须带上音色描述，供编辑页回填。"""
    db, engine = await _build_async_session()
    try:
        db.add_all(
            _seed_project_chapter()
            + [
                Shot(id="s1", chapter_id="c1", index=1, title="镜头一", script_excerpt="小雨：我回来了"),
                Character(
                    id="ch1",
                    project_id="p1",
                    name="小雨",
                    description="25 岁互联网运营",
                    style=ProjectStyle.real_people_city,
                    visual_style=ProjectVisualStyle.live_action,
                    voice_description="青年女声，清亮温柔，语速偏快",
                ),
                ShotCharacterLink(shot_id="s1", character_id="ch1", index=0),
            ]
        )
        await db.commit()

        draft = await build_script_extraction_draft_for_shot(db, "s1")
        assert [char.name for char in draft.characters] == ["小雨"]
        assert [char.voice_description for char in draft.characters] == ["青年女声，清亮温柔，语速偏快"]
    finally:
        await db.close()
        await engine.dispose()


def test_batch_asset_image_tasks_route_returns_201_envelope(monkeypatch) -> None:
    """D-12：HTTP 201 与响应体业务码必须一致（此前是 201 + code=200）。"""
    from app.api.v1.routes.studio import image_tasks as image_tasks_routes

    async def _fake_service(db, *, asset_type, project_id, asset_ids=None):  # noqa: ANN001, ANN202
        return {"tasks": [], "skipped": []}

    async def _fake_db():  # noqa: ANN202
        yield object()

    monkeypatch.setattr(image_tasks_routes, "create_batch_asset_image_tasks_service", _fake_service)
    app.dependency_overrides[get_db] = _fake_db
    try:
        with TestClient(app) as client:
            response = client.post(BATCH_ROUTE, json={"project_id": "p1", "asset_type": "character"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 201
    assert body["data"] == {"tasks": [], "skipped": []}
