"""对白显示名兜底测试：行内 name 为空时用角色库真名填充（工作台字幕/列表展示层）。"""

from __future__ import annotations

import pytest

from app.schemas.studio.shots import ShotDialogLineRead
from app.services.studio.shot_dialogs import _backfill_display_names


class _FakeScalars:
    """``scalars().all()`` 返回预置角色行。"""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:  # noqa: A003
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeDB:
    """最小 DB 替身：execute 返回角色查询结果。"""

    def __init__(self, characters: list) -> None:
        self.characters = characters

    async def execute(self, *_args, **_kwargs):  # noqa: ANN001
        return _FakeExecuteResult(self.characters)


def _char(char_id: str, name: str):
    return type("C", (), {"id": char_id, "name": name})()


def _read(
    *,
    speaker_character_id: str | None = None,
    speaker_name: str | None = None,
    target_character_id: str | None = None,
    target_name: str | None = None,
) -> ShotDialogLineRead:
    return ShotDialogLineRead(
        id=1,
        shot_detail_id="shot-1",
        text="别着急，喝杯热茶。",
        speaker_character_id=speaker_character_id,
        target_character_id=target_character_id,
        speaker_name=speaker_name,
        target_name=target_name,
    )


@pytest.mark.asyncio
async def test_backfill_uses_character_name_when_line_name_empty() -> None:
    """speaker/target 关联了角色但行内 name 为空：应补角色库真名。"""
    db = _FakeDB([_char("char-1", "林夏"), _char("char-2", "陈默")])
    reads = [_read(speaker_character_id="char-1", target_character_id="char-2")]

    result = await _backfill_display_names(db, reads)

    assert result[0].speaker_name == "林夏"
    assert result[0].target_name == "陈默"


@pytest.mark.asyncio
async def test_backfill_keeps_existing_line_name() -> None:
    """行内已有 name：不得被角色库名字覆盖（提取回填优先）。"""
    db = _FakeDB([_char("char-1", "林夏")])
    reads = [_read(speaker_character_id="char-1", speaker_name="林夏（旧称）")]

    result = await _backfill_display_names(db, reads)

    assert result[0].speaker_name == "林夏（旧称）"


@pytest.mark.asyncio
async def test_backfill_skips_query_when_nothing_missing() -> None:
    """所有行都有 name 或未关联角色：不触发角色查询，原样返回。"""

    class _StrictDB:
        async def execute(self, *_args, **_kwargs):  # noqa: ANN001
            raise AssertionError("不应发起角色查询")

    reads = [
        _read(speaker_character_id="char-1", speaker_name="林夏"),
        _read(),
    ]

    result = await _backfill_display_names(_StrictDB(), reads)

    assert result == reads


@pytest.mark.asyncio
async def test_backfill_ignores_unknown_character_id() -> None:
    """关联了不存在的角色 ID：name 保持为空，不报错。"""
    db = _FakeDB([])
    reads = [_read(speaker_character_id="char-missing")]

    result = await _backfill_display_names(db, reads)

    assert result[0].speaker_name is None
