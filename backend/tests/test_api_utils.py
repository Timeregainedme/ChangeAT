"""``app.api.utils.apply_order`` 的排序字段校验测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.utils import apply_order
from app.models.studio import Shot

_ALLOW = {"index", "title", "created_at", "updated_at"}


def test_apply_order_rejects_unknown_field() -> None:
    """回归 P2：非法 order 必须显式报错，不能静默回落到默认排序。

    静默回落会让前端的字段名笔误无声失效——拿到看似正常、顺序却不对的数据。
    错误信息里要带上允许的字段，方便定位。
    """
    with pytest.raises(ValueError, match="Unsupported order field: DROP"):
        apply_order(
            select(Shot),
            model=Shot,
            order="DROP",
            is_desc=True,
            allow_fields=_ALLOW,
            default="index",
        )


def test_apply_order_error_lists_allowed_fields() -> None:
    """报错必须列出允许的字段名（已排序），否则使用者无法自查。"""
    with pytest.raises(ValueError) as excinfo:
        apply_order(
            select(Shot),
            model=Shot,
            order="nope",
            is_desc=False,
            allow_fields=_ALLOW,
            default="index",
        )

    message = str(excinfo.value)
    assert "Allowed fields:" in message
    assert "created_at, index, title, updated_at" in message


def test_apply_order_accepts_allowed_field_and_direction() -> None:
    stmt = apply_order(
        select(Shot),
        model=Shot,
        order="title",
        is_desc=True,
        allow_fields=_ALLOW,
        default="index",
    )
    assert "ORDER BY shots.title DESC" in str(stmt)


def test_apply_order_blank_field_falls_back_to_default() -> None:
    """空串按「未传」处理，仍走默认排序（兼容 ``?order=`` 的写法）。"""
    stmt = apply_order(
        select(Shot),
        model=Shot,
        order="",
        is_desc=False,
        allow_fields=_ALLOW,
        default="index",
    )
    assert "ORDER BY shots.index ASC" in str(stmt)


def test_apply_order_none_falls_back_to_default() -> None:
    stmt = apply_order(
        select(Shot),
        model=Shot,
        order=None,
        is_desc=True,
        allow_fields=_ALLOW,
        default="updated_at",
    )
    assert "ORDER BY shots.updated_at DESC" in str(stmt)
