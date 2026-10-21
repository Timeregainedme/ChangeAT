"""风格目录服务。

风格从「枚举」改为「表」的原因见 `ProjectStyleOption` 的文档：
业务上会持续出现新题材/新画风，用枚举意味着每加一个风格都要改代码发版。

这里只做三件事：
1. 列出目录（按画面表现形式分组、组内按 sort_order）；
2. 增删改（名称在同组内唯一）；
3. 首次访问时用内置枚举做种子，保证升级后行为与原来一致。
"""

from __future__ import annotations

import uuid
from collections import OrderedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.prompts.style_pack import STYLE_PACKS
from app.models.studio import ProjectStyle, ProjectStyleOption, ProjectVisualStyle
from app.services.common import entity_not_found

# 内置风格的中文说明，用于首次种子；用户后续可自行修改。
_BUILTIN_DESCRIPTIONS: dict[str, str] = {
    "真人都市": "现代都市实拍，冷暖对比、窗光与霓虹混合",
    "真人科幻": "近未来实拍，冷蓝青基调与体积光",
    "真人古装": "古装实拍，暖黄烛光与丝绸质感",
    "动漫科幻": "科幻动画，高饱和撞色与发光边缘",
    "动漫3D": "三维渲染动画，柔和全局光照",
    "国漫": "国风动画，低饱和与笔锋线条",
    "水墨画": "水墨渲染，宣纸质地与留白",
}


def _builtin_options() -> list[ProjectStyleOption]:
    """按枚举生成内置种子（保持 UI 原有顺序）。"""
    rows: list[ProjectStyleOption] = []
    for index, item in enumerate(ProjectStyle):
        visual = (
            ProjectVisualStyle.live_action
            if item.name.startswith("real_people_")
            else ProjectVisualStyle.anime
        )
        rows.append(
            ProjectStyleOption(
                id=f"style-{uuid.uuid4().hex[:12]}",
                visual_style=visual.value,
                name=item.value,
                description=_BUILTIN_DESCRIPTIONS.get(item.value, ""),
                # 内置风格沿用原有质感描述，保证升级后出图效果不变
                prompt_pack=STYLE_PACKS.get(item.value, ""),
                sort_order=index,
            )
        )
    return rows


async def ensure_style_catalog(db: AsyncSession) -> None:
    """目录为空时写入内置风格；非空则不动（避免覆盖用户改动）。"""
    existing = await db.scalar(select(ProjectStyleOption).limit(1))
    if existing is not None:
        return

    db.add_all(_builtin_options())
    await db.flush()


async def list_style_options(db: AsyncSession) -> list[ProjectStyleOption]:
    """列出全部风格：先按表现形式分组顺序，再按组内 sort_order。"""
    await ensure_style_catalog(db)
    result = await db.execute(
        select(ProjectStyleOption).order_by(
            ProjectStyleOption.visual_style.asc(),
            ProjectStyleOption.sort_order.asc(),
            ProjectStyleOption.name.asc(),
        )
    )
    rows = list(result.scalars().all())

    # 表现形式按「现实 → 动漫 → 其它」排序，避免字母序把常用项排到后面
    order = {ProjectVisualStyle.live_action.value: 0, ProjectVisualStyle.anime.value: 1}
    rows.sort(key=lambda r: (order.get(r.visual_style, 9), r.sort_order, r.name))
    return rows


def group_style_options(rows: list[ProjectStyleOption]) -> "OrderedDict[str, list[ProjectStyleOption]]":
    """按画面表现形式分组，保持传入顺序。"""
    grouped: OrderedDict[str, list[ProjectStyleOption]] = OrderedDict()
    for row in rows:
        grouped.setdefault(row.visual_style, []).append(row)
    return grouped


async def get_style_option(db: AsyncSession, style_id: str) -> ProjectStyleOption:
    row = await db.get(ProjectStyleOption, style_id)
    if row is None:
        raise ValueError(entity_not_found("ProjectStyle"))
    return row


async def create_style_option(
    db: AsyncSession,
    *,
    visual_style: str,
    name: str,
    description: str = "",
    prompt_pack: str = "",
    sort_order: int | None = None,
) -> ProjectStyleOption:
    """新增风格。

    校验两件事：表现形式非空、同组内名称不重复。
    重名会让项目创建时的「风格 + 表现形式」组合产生歧义，必须挡住。
    """
    visual = (visual_style or "").strip()
    style_name = (name or "").strip()
    if not visual:
        raise ValueError("请选择画面表现形式")
    if not style_name:
        raise ValueError("请填写风格名称")

    await ensure_style_catalog(db)
    duplicated = await db.scalar(
        select(ProjectStyleOption).where(
            ProjectStyleOption.visual_style == visual,
            ProjectStyleOption.name == style_name,
        )
    )
    if duplicated is not None:
        raise ValueError(f"「{visual}」下已存在风格「{style_name}」")

    if sort_order is None:
        # 默认排到该组末尾
        max_order = await db.scalar(
            select(ProjectStyleOption.sort_order)
            .where(ProjectStyleOption.visual_style == visual)
            .order_by(ProjectStyleOption.sort_order.desc())
            .limit(1)
        )
        sort_order = int(max_order or 0) + 1

    row = ProjectStyleOption(
        id=f"style-{uuid.uuid4().hex[:12]}",
        visual_style=visual,
        name=style_name,
        description=(description or "").strip(),
        prompt_pack=(prompt_pack or "").strip(),
        sort_order=sort_order,
    )
    db.add(row)
    await db.flush()
    return row


async def update_style_option(
    db: AsyncSession,
    *,
    style_id: str,
    name: str | None = None,
    description: str | None = None,
    prompt_pack: str | None = None,
    sort_order: int | None = None,
) -> ProjectStyleOption:
    row = await get_style_option(db, style_id)

    if name is not None:
        next_name = name.strip()
        if not next_name:
            raise ValueError("风格名称不能为空")
        if next_name != row.name:
            duplicated = await db.scalar(
                select(ProjectStyleOption).where(
                    ProjectStyleOption.visual_style == row.visual_style,
                    ProjectStyleOption.name == next_name,
                    ProjectStyleOption.id != row.id,
                )
            )
            if duplicated is not None:
                raise ValueError(f"「{row.visual_style}」下已存在风格「{next_name}」")
            row.name = next_name

    if description is not None:
        row.description = description.strip()
    if prompt_pack is not None:
        row.prompt_pack = prompt_pack.strip()
    if sort_order is not None:
        row.sort_order = sort_order

    await db.flush()
    return row


async def delete_style_option(db: AsyncSession, *, style_id: str) -> None:
    """删除风格。

    不阻止「已被项目使用」的删除：历史项目里的 style 是字符串，删掉目录项不会破坏数据，
    只是新建项目时不再出现。若需要强约束，后续可在这里加一次引用计数检查。
    """
    row = await get_style_option(db, style_id)
    await db.delete(row)
    await db.flush()


async def resolve_style_motif(db: AsyncSession, *, style: str) -> str | None:
    """按风格名取出提示词质感描述。

    返回 None 表示「目录里没配」，调用方会回落到内置 `STYLE_PACKS`。
    之所以返回 None 而不是直接给默认值：内置包的回落逻辑只有一处（style_pack），
    在两层各写一份默认值迟早会不一致。
    """
    name = (style or "").strip()
    if not name:
        return None

    row = await db.scalar(
        select(ProjectStyleOption).where(ProjectStyleOption.name == name).limit(1)
    )
    if row is None:
        return None
    text = (row.prompt_pack or "").strip()
    return text or None
