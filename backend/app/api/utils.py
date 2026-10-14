"""API 通用工具：列表过滤、排序、分页。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import Select
from sqlalchemy.ext.asyncio import AsyncSession


def normalize_q(q: str | None) -> str | None:
    if q is None:
        return None
    s = q.strip()
    return s or None


def apply_keyword_filter(
    stmt: Select[Any],
    *,
    q: str | None,
    fields: Sequence[InstrumentedAttribute[Any]],
) -> Select[Any]:
    qn = normalize_q(q)
    if not qn or not fields:
        return stmt
    pattern = f"%{qn}%"
    cond = None
    for f in fields:
        expr = f.ilike(pattern)
        cond = expr if cond is None else (cond | expr)
    return stmt.where(cond) if cond is not None else stmt


def apply_order(
    stmt: Select[Any],
    *,
    model: Any,
    order: str | None,
    is_desc: bool,
    allow_fields: set[str],
    default: str,
) -> Select[Any]:
    if order and order not in allow_fields:
        # 静默回落到默认排序会让前端的字段名笔误无声失效（拿到看似正常、顺序却不对的
        # 数据），这里改成显式报错，错误信息带上允许的字段方便定位。空串仍按未传处理。
        allowed = ", ".join(sorted(allow_fields))
        raise ValueError(f"Unsupported order field: {order}. Allowed fields: {allowed}")
    col = order or default
    attr = getattr(model, col)
    return stmt.order_by(attr.desc() if is_desc else attr.asc())


async def paginate(
    db: AsyncSession,
    *,
    stmt: Select[Any],
    page: int,
    page_size: int,
) -> tuple[list[Any], int]:
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await db.execute(count_stmt)
    total = int(total_res.scalar() or 0)

    res = await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    items = list(res.scalars().all())
    return items, total

