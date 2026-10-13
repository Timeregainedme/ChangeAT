"""台词情绪（emotion）贯通测试 —— 提示词改造第 2 档 F 项。

背景：脚本提取链路的 LLM 契约（`app/schemas/skills/common.py` 的 `DialogLine`）早就产出
`emotion`，优云智算 IndexTTS-2.5 也支持 `emotion_description`，但两张表都没有这一列，
提取到的情绪被静默丢弃，配音时只能手输 —— 属于真实的数据丢失缺陷（迁移 013 补列）。

本文件保护三件事：
1. `_clean_emotion` 的归一化与截断（varchar(64)，超长必须截断而不是让 MySQL 报错）；
2. 提取构建 `_build_candidates_from_shot_draft` 会把 emotion 带给候选；
3. `mark_accepted` 把候选上的 emotion 写到正式台词行，且接受时的显式覆盖优先。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.studio import DialogueLineMode, ShotDetail, ShotDialogLine, ShotExtractedDialogueCandidate
from app.schemas.studio.shots import ShotExtractedDialogueCandidateAcceptRequest
from app.services.studio import shot_extracted_dialogue_candidates as candidates_mod
from app.services.studio.shot_extracted_dialogue_candidates import (
    _build_candidates_from_shot_draft,
    _clean_emotion,
    mark_accepted,
)


class _FakeExecuteResult:
    """`_resolve_dialog_index` 用 `.first()` 判断 index 是否冲突；这里恒为「不冲突」。"""

    def first(self):  # noqa: ANN201
        return None


class _FakeDB:
    """最小 DB 替身：覆盖 `mark_accepted` 用到的 get/execute/scalar/add/flush/refresh。"""

    def __init__(self, *, candidates: dict, details: dict) -> None:
        self.candidates = dict(candidates)
        self.details = dict(details)
        self.added: list = []

    async def get(self, model, entity_id):  # noqa: ANN001, ANN201
        if model is ShotExtractedDialogueCandidate:
            return self.candidates.get(entity_id)
        if model is ShotDetail:
            return self.details.get(entity_id)
        return None

    async def execute(self, *_args, **_kwargs):  # noqa: ANN001, ANN201
        return _FakeExecuteResult()

    async def scalar(self, *_args, **_kwargs):  # noqa: ANN001, ANN201
        return 0

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    async def flush(self) -> None:
        # 模拟数据库分配自增主键，供 `line.id = ...` 使用。
        for obj in self.added:
            if isinstance(obj, ShotDialogLine) and getattr(obj, "id", None) is None:
                obj.id = 1

    async def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


async def _noop_recompute(_db, *, shot_id: str) -> None:  # noqa: ANN001
    return None


def _draft_item(**kwargs) -> SimpleNamespace:
    base = {
        "text": "你凭什么这样说！",
        "index": 0,
        "line_mode": DialogueLineMode.dialogue,
        "speaker_name": "林晚",
        "target_name": "顾言",
        "emotion": "愤怒",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _candidate(*, emotion: str | None) -> ShotExtractedDialogueCandidate:
    return ShotExtractedDialogueCandidate(
        id=5,
        shot_id="shot-1",
        index=0,
        text="你凭什么这样说！",
        line_mode=DialogueLineMode.dialogue,
        emotion=emotion,
    )


# --------------------------------------------------------------------------- #
# _clean_emotion
# --------------------------------------------------------------------------- #


def test_clean_emotion_normalizes_blank_to_none() -> None:
    assert _clean_emotion(None) is None
    assert _clean_emotion("") is None
    assert _clean_emotion("   ") is None


def test_clean_emotion_strips_and_truncates_to_column_width() -> None:
    assert _clean_emotion("  愤怒 ") == "愤怒"
    long_value = "愤" * 100
    assert len(_clean_emotion(long_value)) == 64


# --------------------------------------------------------------------------- #
# 提取构建：emotion 进入候选
# --------------------------------------------------------------------------- #


def test_build_candidates_carries_emotion() -> None:
    draft = SimpleNamespace(dialogue_lines=[_draft_item()])
    built = _build_candidates_from_shot_draft(draft)
    assert len(built) == 1
    assert built[0]["emotion"] == "愤怒"
    assert built[0]["text"] == "你凭什么这样说！"


def test_build_candidates_drops_blank_emotion() -> None:
    draft = SimpleNamespace(dialogue_lines=[_draft_item(emotion="  ")])
    built = _build_candidates_from_shot_draft(draft)
    assert built[0]["emotion"] is None


def test_build_candidates_skips_empty_text() -> None:
    draft = SimpleNamespace(dialogue_lines=[_draft_item(text="   ")])
    assert _build_candidates_from_shot_draft(draft) == []


# --------------------------------------------------------------------------- #
# 接受候选：emotion 落到正式台词行
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_mark_accepted_carries_candidate_emotion(monkeypatch) -> None:
    monkeypatch.setattr(candidates_mod, "recompute_shot_status", _noop_recompute)
    db = _FakeDB(candidates={5: _candidate(emotion="愤怒")}, details={"shot-1": object()})

    await mark_accepted(db, candidate_id=5)

    assert len(db.added) == 1
    line = db.added[0]
    assert isinstance(line, ShotDialogLine)
    assert line.emotion == "愤怒"
    assert line.shot_detail_id == "shot-1"


@pytest.mark.asyncio
async def test_mark_accepted_accept_request_overrides_emotion(monkeypatch) -> None:
    monkeypatch.setattr(candidates_mod, "recompute_shot_status", _noop_recompute)
    db = _FakeDB(candidates={5: _candidate(emotion="愤怒")}, details={"shot-1": object()})

    await mark_accepted(
        db,
        candidate_id=5,
        body=ShotExtractedDialogueCandidateAcceptRequest(emotion="轻声哽咽"),
    )

    line = db.added[0]
    assert line.emotion == "轻声哽咽"


@pytest.mark.asyncio
async def test_mark_accepted_without_emotion_stays_none(monkeypatch) -> None:
    monkeypatch.setattr(candidates_mod, "recompute_shot_status", _noop_recompute)
    db = _FakeDB(candidates={5: _candidate(emotion=None)}, details={"shot-1": object()})

    await mark_accepted(db, candidate_id=5)

    assert db.added[0].emotion is None
