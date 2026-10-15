"""对白显示名统一口径测试（批次 2：角色真名 / 对白显示名链路）。

统一口径：台词行能解析到 ``speaker_character_id`` / ``target_character_id`` 时显示角色表
**当前**名字，解析不到才回落行内 ``speaker_name`` / ``target_name``。

覆盖范围：

- 服务层（真实内存 sqlite）：角色改名、角色被删除、角色名为空、行内名字空串与 null 稳定、
  旁白（VOICE_OVER）、仅 target 缺失、同名角色按 ID 解析、接受候选写入角色 ID、
  同镜头同名候选全部同步；
- 接线层：``build_shot_preparation_state`` 的 ``saved_dialogue_lines`` 复用同一口径；
- 路由层（TestClient + 假 DB）：分页接口返回角色真名，且空串不会被吞成 null。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.studio import (
    CameraAngle,
    CameraMovement,
    CameraShotType,
    Chapter,
    Character,
    DialogueLineMode,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Shot,
    ShotCandidateStatus,
    ShotCandidateType,
    ShotDetail,
    ShotDialogLine,
    ShotDialogueCandidateStatus,
    ShotExtractedCandidate,
    ShotExtractedDialogueCandidate,
    ShotStatus,
)
from app.schemas.studio.shots import (
    ShotAssetsOverviewRead,
    ShotAssetsOverviewSummary,
    ShotExtractedDialogueCandidateAcceptRequest,
    ShotExtractionSummaryRead,
    ShotRead,
)
from app.services.studio import shot_preparation_state as preparation_state_service
from app.services.studio.shot_dialogs import list_by_shot, pick_display_name
from app.services.studio.shot_extracted_candidates import (
    mark_linked_by_name,
    mark_pending_by_linked_entity,
    mark_pending_by_name,
)
from app.services.studio.shot_extracted_dialogue_candidates import mark_accepted


# --------------------------------------------------------------------------------------
# 服务层：真实内存 sqlite
# --------------------------------------------------------------------------------------


async def _build_session() -> tuple[AsyncSession, object]:
    """构建内存 sqlite 会话：走真实 SQL，验证显示名口径的端到端行为。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


def _character(character_id: str, name: str, *, project_id: str = "p1") -> Character:
    """构造角色行（同名角色只能出现在不同项目：``uq_characters_project_name``）。"""
    return Character(
        id=character_id,
        project_id=project_id,
        name=name,
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )


def _project(project_id: str, name: str) -> Project:
    """构造项目行。"""
    return Project(
        id=project_id,
        name=name,
        description="",
        style=ProjectStyle.real_people_city,
        visual_style=ProjectVisualStyle.live_action,
    )


async def _seed_shot_graph(db: AsyncSession) -> None:
    """写入项目/章节/镜头/镜头细节与两个角色，作为显示名解析的真实外键图。"""
    db.add_all(
        [
            _project("p1", "项目一"),
            Chapter(id="c1", project_id="p1", index=1, title="第一章"),
            Shot(id="s1", chapter_id="c1", index=1, title="镜头一"),
            ShotDetail(
                id="s1",
                camera_shot=CameraShotType.ms,
                angle=CameraAngle.eye_level,
                movement=CameraMovement.static,
                duration=4,
                action_beats=["推门进入"],
            ),
            _character("char-1", "林夏"),
            _character("char-2", "陈默"),
        ]
    )
    await db.commit()


def _dialog_line(index: int, **overrides: object) -> ShotDialogLine:
    """构造待落库的台词行。"""
    params: dict[str, object] = {
        "shot_detail_id": "s1",
        "index": index,
        "text": "别着急，喝杯热茶。",
    }
    params.update(overrides)
    return ShotDialogLine(**params)


def _dialogue_candidate(**overrides: object) -> ShotExtractedDialogueCandidate:
    """构造待落库的对白候选。"""
    params: dict[str, object] = {
        "shot_id": "s1",
        "index": 0,
        "text": "别着急，喝杯热茶。",
        "line_mode": DialogueLineMode.dialogue,
        "candidate_status": ShotDialogueCandidateStatus.pending,
        "source": "extraction",
    }
    params.update(overrides)
    return ShotExtractedDialogueCandidate(**params)


def _asset_candidate(name: str, **overrides: object) -> ShotExtractedCandidate:
    """构造待落库的资产候选（默认角色类型、pending）。"""
    params: dict[str, object] = {
        "shot_id": "s1",
        "candidate_type": ShotCandidateType.character,
        "candidate_name": name,
        "candidate_status": ShotCandidateStatus.pending,
        "source": "extraction",
    }
    params.update(overrides)
    return ShotExtractedCandidate(**params)


@pytest.mark.asyncio
async def test_list_by_shot_prefers_current_character_name_after_rename() -> None:
    """角色改名后：台词行显示角色表当前名字，而不是行内残留旧名（B-1）。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        db.add(_dialog_line(0, speaker_character_id="char-1", speaker_name="林夏（旧称）"))
        await db.commit()

        character = await db.get(Character, "char-1")
        character.name = "林夏"
        await db.commit()

        reads = await list_by_shot(db, shot_id="s1")

    assert [read.speaker_name for read in reads] == ["林夏"]


@pytest.mark.asyncio
async def test_list_by_shot_falls_back_to_line_name_when_character_deleted() -> None:
    """角色被删除（行上残留历史角色 ID）：回落行内名字，不报错也不显示空（B-1/C-7）。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        db.add(_dialog_line(0, speaker_character_id="char-1", speaker_name="林夏（旧称）"))
        await db.commit()

        await db.delete(await db.get(Character, "char-1"))
        await db.commit()

        reads = await list_by_shot(db, shot_id="s1")

    assert [read.speaker_name for read in reads] == ["林夏（旧称）"]


@pytest.mark.asyncio
async def test_list_by_shot_keeps_empty_string_and_none_apart() -> None:
    """D-1：解析不到角色时空串保持空串、null 保持 null，字段类型不漂移。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        db.add_all(
            [
                _dialog_line(0, speaker_name="", target_name=None),
                _dialog_line(1, speaker_name=None, target_name=""),
            ]
        )
        await db.commit()

        reads = await list_by_shot(db, shot_id="s1")

    assert [read.speaker_name for read in reads] == ["", None]
    assert [read.target_name for read in reads] == [None, ""]


@pytest.mark.asyncio
async def test_list_by_shot_resolves_target_only() -> None:
    """target_name 单独缺失：只解析 target，speaker 保持原值（C-7）。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        db.add(_dialog_line(0, speaker_name="", target_character_id="char-2", target_name=None))
        await db.commit()

        reads = await list_by_shot(db, shot_id="s1")

    assert reads[0].speaker_name == ""
    assert reads[0].target_name == "陈默"


@pytest.mark.asyncio
async def test_list_by_shot_keeps_same_named_characters_apart() -> None:
    """同名角色（跨项目）：显示名按角色 ID 解析而不是按名字匹配，改名互不影响。

    说明：``uq_characters_project_name`` 只保证项目内不同名，跨项目重名是常态；
    若解析按名字匹配，改其中一个角色就会串改另一个项目的台词显示名。
    """
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        db.add_all([_project("p2", "项目二"), _character("char-b", "小雨", project_id="p2")])
        db.add(_character("char-a", "小雨"))
        await db.commit()

        line_a = _dialog_line(0, speaker_character_id="char-a", speaker_name="小雨")
        line_b = _dialog_line(1, speaker_character_id="char-b", speaker_name="小雨")
        db.add_all([line_a, line_b])
        await db.commit()

        renamed = await db.get(Character, "char-b")
        renamed.name = "大雨"
        await db.commit()

        reads = await list_by_shot(db, shot_id="s1")

    names = {read.id: read.speaker_name for read in reads}
    assert names[line_a.id] == "小雨"
    assert names[line_b.id] == "大雨"


@pytest.mark.asyncio
async def test_accept_dialogue_candidate_writes_character_ids() -> None:
    """B-2：接受候选时按名字解析并写入角色 ID，角色改名后行内名字随之更新。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        candidate = _dialogue_candidate(speaker_name="林夏", target_name="陈默")
        db.add(candidate)
        await db.commit()

        await mark_accepted(db, candidate_id=candidate.id)

        line = (await db.execute(select(ShotDialogLine))).scalars().one()
        assert line.speaker_character_id == "char-1"
        assert line.target_character_id == "char-2"
        # 行内名字保留（数据库真值），但展示层以角色真名为准
        assert line.speaker_name == "林夏"

        renamed = await db.get(Character, "char-1")
        renamed.name = "林夏（新名）"
        await db.commit()

        reads = await list_by_shot(db, shot_id="s1")

    assert [read.speaker_name for read in reads] == ["林夏（新名）"]
    assert [read.target_name for read in reads] == ["陈默"]


@pytest.mark.asyncio
async def test_accept_dialogue_candidate_resolves_override_name() -> None:
    """接受请求里覆盖的角色名同样参与解析（不能只认候选自带名字）。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        candidate = _dialogue_candidate(speaker_name="路人甲")
        db.add(candidate)
        await db.commit()

        await mark_accepted(
            db,
            candidate_id=candidate.id,
            body=ShotExtractedDialogueCandidateAcceptRequest(speaker_name="陈默"),
        )

        line = (await db.execute(select(ShotDialogLine))).scalars().one()

    assert line.speaker_name == "陈默"
    assert line.speaker_character_id == "char-2"


@pytest.mark.asyncio
async def test_accept_dialogue_candidate_keeps_id_empty_for_unknown_name() -> None:
    """名字在项目角色表里查不到：不写入角色 ID，展示层回落行内名字。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        candidate = _dialogue_candidate(speaker_name="路人甲")
        db.add(candidate)
        await db.commit()

        await mark_accepted(db, candidate_id=candidate.id)

        line = (await db.execute(select(ShotDialogLine))).scalars().one()
        reads = await list_by_shot(db, shot_id="s1")

    assert line.speaker_character_id is None
    assert [read.speaker_name for read in reads] == ["路人甲"]


@pytest.mark.asyncio
async def test_accept_dialogue_candidate_ignores_other_project_same_name() -> None:
    """接受候选时的角色解析限定在本项目内：别的项目有同名角色不算命中。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        db.add_all([_project("p2", "项目二"), _character("char-b", "小雨", project_id="p2")])
        await db.commit()

        candidate = _dialogue_candidate(speaker_name="小雨")
        db.add(candidate)
        await db.commit()

        await mark_accepted(db, candidate_id=candidate.id)

        line = (await db.execute(select(ShotDialogLine))).scalars().one()
        reads = await list_by_shot(db, shot_id="s1")

    assert line.speaker_character_id is None
    assert [read.speaker_name for read in reads] == ["小雨"]


@pytest.mark.asyncio
async def test_accept_voice_over_candidate_keeps_no_speaker() -> None:
    """旁白（VOICE_OVER）：不得凭空关联角色；模式由前端回落显示「旁白」。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        candidate = _dialogue_candidate(
            text="三年后，出租屋的灯还亮着。",
            line_mode=DialogueLineMode.voice_over,
            speaker_name=None,
            target_name=None,
        )
        db.add(candidate)
        await db.commit()

        await mark_accepted(db, candidate_id=candidate.id)

        line = (await db.execute(select(ShotDialogLine))).scalars().one()
        reads = await list_by_shot(db, shot_id="s1")

    assert line.line_mode == DialogueLineMode.voice_over
    assert line.speaker_character_id is None
    assert line.speaker_name is None
    assert [read.speaker_name for read in reads] == [None]


class _MultiRowResult:
    """多行候选替身结果集：满足 ``scalars().all()`` 即可。"""

    def __init__(self, rows: list) -> None:
        self._rows = list(rows)

    def scalars(self) -> "_MultiRowResult":
        return self

    def all(self) -> list:
        return self._rows


class _MultiRowCandidateDB:
    """假 DB：让 ``mark_*_by_name`` 匹配到多行候选。

    真实库上 ``shot_extracted_candidates`` 带唯一约束
    ``uq_shot_candidate_name (shot_id, candidate_type, candidate_name)``，
    同镜头同类型同名候选至多一行，只能用替身验证「全部匹配」语义。
    """

    def __init__(self, rows: list) -> None:
        self.rows = rows

    async def execute(self, _stmt: object) -> _MultiRowResult:
        return _MultiRowResult(self.rows)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None

    async def get(self, _model: object, entity_id: str) -> object:
        return SimpleNamespace(id=entity_id, skip_extraction=True, status=ShotStatus.pending)


@pytest.mark.asyncio
async def test_mark_linked_and_pending_by_name_sync_every_match() -> None:
    """D-8：命中多行同名候选时全部置 linked；回退时也全部置回 pending。"""
    rows = [_asset_candidate("小雨"), _asset_candidate("小雨")]
    db = _MultiRowCandidateDB(rows)

    linked = await mark_linked_by_name(
        db,
        shot_id="s1",
        candidate_type="character",
        candidate_name="小雨",
        linked_entity_id="char-1",
    )
    after_link = [(row.candidate_status, row.linked_entity_id) for row in rows]

    await mark_pending_by_name(
        db,
        shot_id="s1",
        candidate_type="character",
        candidate_name="小雨",
    )
    after_pending = [(row.candidate_status, row.linked_entity_id) for row in rows]

    assert linked is rows[0]
    assert after_link == [
        (ShotCandidateStatus.linked, "char-1"),
        (ShotCandidateStatus.linked, "char-1"),
    ]
    assert after_pending == [(ShotCandidateStatus.pending, None), (ShotCandidateStatus.pending, None)]


@pytest.mark.asyncio
async def test_mark_pending_by_linked_entity_resets_all_matching_candidates() -> None:
    """解除关联：同一实体被多行不同名候选引用时，全部回退为 pending。

    ``linked_entity_id`` 上没有唯一约束，多行命中是可达场景（同一角色被两种写法各生成
    一条候选时），只回退第一条会让剩余候选永久停在 linked，镜头状态再也回不到 pending。
    """
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        db.add_all(
            [
                _asset_candidate(
                    "小雨",
                    candidate_status=ShotCandidateStatus.linked,
                    linked_entity_id="char-1",
                ),
                _asset_candidate(
                    "小宇",
                    candidate_status=ShotCandidateStatus.linked,
                    linked_entity_id="char-1",
                ),
                _asset_candidate(
                    "阿念",
                    candidate_status=ShotCandidateStatus.linked,
                    linked_entity_id="char-9",
                ),
            ]
        )
        await db.commit()

        await mark_pending_by_linked_entity(
            db,
            shot_id="s1",
            candidate_type="character",
            linked_entity_id="char-1",
        )
        rows = list(
            (
                await db.execute(select(ShotExtractedCandidate).order_by(ShotExtractedCandidate.id.asc()))
            )
            .scalars()
            .all()
        )

    assert [row.candidate_status for row in rows] == [
        ShotCandidateStatus.pending,
        ShotCandidateStatus.pending,
        ShotCandidateStatus.linked,
    ]
    assert [row.linked_entity_id for row in rows] == [None, None, "char-9"]


@pytest.mark.asyncio
async def test_preparation_state_saved_lines_use_display_name_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-1 接线：build_shot_preparation_state 的 saved_dialogue_lines 复用统一口径。"""
    db, engine = await _build_session()
    async with db:
        await _seed_shot_graph(db)
        db.add(_dialog_line(0, speaker_character_id="char-1", speaker_name="林夏（旧称）"))
        await db.commit()

        renamed = await db.get(Character, "char-1")
        renamed.name = "林夏"
        await db.commit()

        async def _fake_get_shot(*_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(id="s1")

        async def _fake_build_shot_read(*_args: object, **_kwargs: object) -> ShotRead:
            return ShotRead(
                id="s1",
                chapter_id="c1",
                index=1,
                title="镜头一",
                script_excerpt="剧本摘录",
                status=ShotStatus.ready,
                extraction=ShotExtractionSummaryRead(state="extracted_resolved", has_extracted=True),
            )

        async def _fake_get_shot_detail(*_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                camera_shot="MS",
                angle="EYE_LEVEL",
                movement="STATIC",
                duration=4,
                action_beats=["推门进入"],
            )

        async def _fake_assets_overview(*_args: object, **_kwargs: object) -> ShotAssetsOverviewRead:
            return ShotAssetsOverviewRead(
                shot_id="s1",
                skip_extraction=False,
                status=ShotStatus.ready,
                summary=ShotAssetsOverviewSummary(
                    linked_count=0,
                    pending_count=0,
                    ignored_count=0,
                    total_count=0,
                ),
            )

        monkeypatch.setattr(preparation_state_service, "get_shot", _fake_get_shot)
        monkeypatch.setattr(preparation_state_service, "build_shot_read", _fake_build_shot_read)
        monkeypatch.setattr(preparation_state_service, "get_shot_detail", _fake_get_shot_detail)
        monkeypatch.setattr(preparation_state_service, "get_shot_assets_overview", _fake_assets_overview)

        state = await preparation_state_service.build_shot_preparation_state(db, shot_id="s1")

    assert [line.speaker_name for line in state.saved_dialogue_lines] == ["林夏"]
    assert state.pending_confirm_count == 0
    assert state.ready_for_generation is True


# --------------------------------------------------------------------------------------
# 纯函数：显示名挑选
# --------------------------------------------------------------------------------------


def test_pick_display_name_prefers_character_and_keeps_fallback_type() -> None:
    """真名优先；解析不到角色时原样回落（空串仍是空串、None 仍是 None）。"""
    assert pick_display_name({"char-1": "林夏"}, character_id="char-1", fallback_name="旧名") == "林夏"
    assert pick_display_name({}, character_id="char-1", fallback_name="") == ""
    assert pick_display_name({}, character_id="char-1", fallback_name=None) is None
    assert pick_display_name({}, character_id=None, fallback_name="行内名") == "行内名"


# --------------------------------------------------------------------------------------
# 路由层：分页接口 + 假 DB
# --------------------------------------------------------------------------------------


class _RouteResult:
    """路由假 DB 结果集：同时支持 count 的 scalar() 与行查询的 scalars().all()/first()。"""

    def __init__(self, *, scalar: int | None = None, rows: list | None = None) -> None:
        self._scalar = scalar
        self._rows = list(rows or [])

    def scalar(self) -> int | None:
        return self._scalar

    def scalars(self) -> "_RouteResult":
        return self

    def all(self) -> list:
        return self._rows

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None


class _DialogRouteDB:
    """分页路由假 DB：按 SQL 文本区分「总数 / 角色 / 台词行」三类查询。"""

    def __init__(self, lines: list, characters: list) -> None:
        self._lines = list(lines)
        self._characters = list(characters)

    async def execute(self, stmt: object) -> _RouteResult:  # noqa: ANN001
        text = str(stmt)
        if "count(*)" in text:
            return _RouteResult(scalar=len(self._lines))
        if "FROM characters" in text:
            return _RouteResult(rows=self._characters)
        return _RouteResult(rows=self._lines)


def _override_db(db: object):
    """把假 DB 注入路由依赖（与仓库其它路由级测试一致）。"""

    async def _get_db() -> AsyncGenerator[object, None]:
        yield db

    return _get_db


def _route_line(**overrides: object) -> ShotDialogLine:
    """构造未落库的台词行替身，用于路由级读模型序列化。"""
    params: dict[str, object] = {
        "id": 1,
        "shot_detail_id": "shot-1",
        "index": 0,
        "text": "别着急，喝杯热茶。",
        "line_mode": DialogueLineMode.dialogue,
    }
    params.update(overrides)
    return ShotDialogLine(**params)


def test_paginated_route_returns_character_true_name(client: TestClient) -> None:
    """路由级：分页接口按角色 ID 返回当前真名，空串保持空串（B-1/D-1）。"""
    db = _DialogRouteDB(
        lines=[_route_line(speaker_character_id="char-1", speaker_name="林夏（旧称）", target_name="")],
        characters=[SimpleNamespace(id="char-1", name="林夏")],
    )
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.get(
            "/api/v1/studio/shot-dialog-lines",
            params={"shot_detail_id": "shot-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["pagination"]["total"] == 1
    item = body["data"]["items"][0]
    assert item["speaker_name"] == "林夏"
    assert item["target_name"] == ""


def test_paginated_route_falls_back_when_character_deleted(client: TestClient) -> None:
    """路由级：角色已被删除（查询不到角色行）时回落行内名字，不返回空。"""
    db = _DialogRouteDB(
        lines=[_route_line(speaker_character_id="char-missing", speaker_name="林夏（旧称）")],
        characters=[],
    )
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.get(
            "/api/v1/studio/shot-dialog-lines",
            params={"shot_detail_id": "shot-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["data"]["items"][0]["speaker_name"] == "林夏（旧称）"
