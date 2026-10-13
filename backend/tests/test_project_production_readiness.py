"""项目开工预检服务测试。

重点锁住一个真实缺陷的回归：项目级预检的「信息提取确认」必须与分镜级就绪门禁口径一致。
分镜门禁要求 `Shot.last_extracted_at` 非空（见 `shot_video_readiness` 的 `extraction_ready`），
只统计「待确认候选」会让一个从未跑过提取的项目通过预检，随后每个分镜发起视频生成时被 409 拦住。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.studio import Project
from app.services.studio.project_production_readiness import (
    get_project_production_readiness,
)


class _Scalars:
    def __init__(self, rows: list[str]) -> None:
        self._rows = rows

    def all(self) -> list[str]:
        return list(self._rows)


class _ExecuteResult:
    def __init__(self, rows: list[str]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _FakeReadinessDB:
    """按 SQL 文本分派的替身，只需支撑预检用到的聚合查询。

    `rules` 是有序的 (SQL 子串, 返回值) 列表，先匹配到的生效 —— 顺序很重要，
    例如 `shot_extracted_dialogue_candidates` 必须先于 `shot_extracted_candidates`
    匹配，`voice_id` 必须先于 `characters`。
    """

    def __init__(self, *, rules: list[tuple[str, int]], shot_ids: tuple[str, ...] = ("shot-1",)) -> None:
        self._rules = rules
        self._shot_ids = list(shot_ids)
        self.sql_log: list[str] = []

    async def get(self, model, entity_id):  # noqa: ANN001, ANN201
        if model is Project:
            return SimpleNamespace(
                style="真人都市",
                visual_style="现实",
                default_video_ratio=None,
            )
        # ModelSettings 取不到 => 四个默认模型检查都走「未配置」分支，不触碰 Provider/Model。
        return None

    async def execute(self, stmt):  # noqa: ANN001, ANN201
        return _ExecuteResult(self._shot_ids)

    async def scalar(self, stmt):  # noqa: ANN001, ANN201
        sql = str(stmt)
        self.sql_log.append(sql)
        for marker, value in self._rules:
            if marker in sql:
                return value
        return 0


_BASE_RULES: list[tuple[str, int]] = [
    ("shot_extracted_dialogue_candidates", 0),
    ("shot_extracted_candidates", 0),
    ("skip_extraction", 0),
    ("shot_frame_images", 1),
    ("override_video_ratio", 1),
    ("chapters", 1),
    ("voice_id", 1),
    ("characters", 1),
]


def _rules(**overrides: int) -> list[tuple[str, int]]:
    return [(marker, overrides.get(marker, value)) for marker, value in _BASE_RULES]


async def _extraction_check(db: _FakeReadinessDB):  # noqa: ANN202
    result = await get_project_production_readiness(db, project_id="proj-1")
    return next(check for check in result.checks if check.key == "extraction_confirmed_ready")


@pytest.mark.asyncio
async def test_extraction_check_fails_when_shots_were_never_extracted() -> None:
    db = _FakeReadinessDB(rules=_rules(skip_extraction=1))

    check = await _extraction_check(db)

    assert check.ok is False
    assert "还有 1/1 个分镜未完成信息提取" == check.message
    assert check.detail["not_extracted_shots"] == 1


@pytest.mark.asyncio
async def test_extraction_check_fails_on_pending_candidates() -> None:
    db = _FakeReadinessDB(rules=_rules(shot_extracted_candidates=2))

    check = await _extraction_check(db)

    assert check.ok is False
    assert "资产 2 项" in check.message
    assert check.detail["pending_assets"] == 2
    assert check.detail["not_extracted_shots"] == 0


@pytest.mark.asyncio
async def test_extraction_check_reports_both_reasons_when_both_apply() -> None:
    db = _FakeReadinessDB(rules=_rules(skip_extraction=1, shot_extracted_dialogue_candidates=3))

    check = await _extraction_check(db)

    assert check.ok is False
    assert "未完成信息提取" in check.message
    assert "对白 3 项" in check.message
    assert check.detail["not_extracted_shots"] == 1
    assert check.detail["pending_dialogues"] == 3


@pytest.mark.asyncio
async def test_extraction_check_passes_when_all_shots_extracted_and_confirmed() -> None:
    db = _FakeReadinessDB(rules=_rules())

    check = await _extraction_check(db)

    assert check.ok is True
    assert check.message == "提取结果已全部确认"
    assert check.detail == {
        "pending_assets": 0,
        "pending_dialogues": 0,
        "not_extracted_shots": 0,
    }
