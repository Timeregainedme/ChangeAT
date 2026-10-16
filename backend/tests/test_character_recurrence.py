"""角色「是否反复出现」判定的测试。

为什么要锁住这条口径：角色要不要绑定演员直接决定用户建角色卡时的必填项。
用户口径（m09145）是「主角才需要，只在一集内出现的不需要」，
判定依据是角色出现在几个**不同章节**里 —— 因此这里的核心断言就是章节数的边界（1 → 否，2 → 是），
以及「还没有挂过任何分镜」的角色必须与「只在一集出现」同等对待（都不要求绑演员）。
"""

from __future__ import annotations

import pytest

from app.models.studio import Character
from app.services.studio.character_recurrence import (
    RECURRING_MIN_CHAPTERS,
    character_chapter_count,
    character_chapter_counts,
    get_project_character_recurrence,
    is_recurring,
)


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeDB:
    """按「先注册先匹配」的 SQL 子串分派替身。"""

    def __init__(
        self,
        *,
        count_rows: list[tuple[str, int]] | None = None,
        character_ids: list[str] | None = None,
        single_count: int = 0,
    ) -> None:
        self._count_rows = count_rows or []
        self._character_ids = character_ids or []
        self._single_count = single_count

    async def execute(self, stmt):  # noqa: ANN001, ANN201
        # SQLAlchemy 渲染的是大写 GROUP BY，故统一转小写后再判定，避免测试锁死渲染大小写。
        assert "group by" in str(stmt).lower()
        return _Rows(self._count_rows)

    async def scalar(self, stmt):  # noqa: ANN001, ANN201
        assert "count" in str(stmt).lower()
        return self._single_count

    async def scalars(self, stmt):  # noqa: ANN001, ANN201
        assert "characters.id" in str(stmt)
        return _Rows(self._character_ids)


def test_is_recurring_threshold() -> None:
    """边界：0/1 集不算主角级，达到 RECURRING_MIN_CHAPTERS 才算。"""
    assert RECURRING_MIN_CHAPTERS == 2
    assert is_recurring(0) is False
    assert is_recurring(1) is False
    assert is_recurring(2) is True
    assert is_recurring(5) is True


@pytest.mark.asyncio
async def test_character_chapter_counts_maps_ids_to_distinct_chapter_counts() -> None:
    """按项目聚合的结果要以角色 ID 为键，缺失的角色由调用方按 0 处理。"""
    db = _FakeDB(count_rows=[("char-1", 3), ("char-2", 1)])

    counts = await character_chapter_counts(db, project_id="proj-1")

    assert counts == {"char-1": 3, "char-2": 1}


@pytest.mark.asyncio
async def test_character_chapter_counts_tolerates_none_count() -> None:
    """聚合查询在无匹配行时可能给出 None，必须落成 0 而不是抛异常。"""
    db = _FakeDB(count_rows=[("char-1", None)])

    counts = await character_chapter_counts(db, project_id="proj-1")

    assert counts == {"char-1": 0}


@pytest.mark.asyncio
async def test_character_chapter_count_returns_int() -> None:
    """单角色计数供生成链路使用，必须是 int（用于比较阈值）。"""
    db = _FakeDB(single_count=2)

    assert await character_chapter_count(db, character_id="char-1") == 2


@pytest.mark.asyncio
async def test_get_project_character_recurrence_includes_zero_chapter_characters() -> None:
    """完整映射：没有分镜关联的角色也必须出现在结果里，否则前端查不到自己而误判。"""
    db = _FakeDB(count_rows=[("char-1", 2)], character_ids=["char-1", "char-2"])

    result = await get_project_character_recurrence(db, project_id="proj-1")

    assert result.project_id == "proj-1"
    assert result.min_chapters == RECURRING_MIN_CHAPTERS
    assert [(item.character_id, item.chapter_count, item.recurring) for item in result.items] == [
        ("char-1", 2, True),
        ("char-2", 0, False),
    ]


def test_character_model_actor_id_is_optional() -> None:
    """模型层必须允许 actor_id 为空：主角级要求是业务口径，不是数据库约束。"""
    column = Character.__table__.c.actor_id

    assert column.nullable is True
