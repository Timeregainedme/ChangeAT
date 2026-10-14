"""运行时 Agent 系统提示词注册表。

背景：12 个 Agent 的 `_*_SYSTEM_PROMPT` 硬编码在代码里，用户无法在「提示词模板」
页面调整。本模块把「模板表已发布（published_at 非空）的 agent_* 模板」接入
AgentBase.system_prompt：发布后覆盖代码默认，未发布/恢复默认则回落代码默认。

生效模型（用户选择「保存后手动触发生效」）：
- 模板页「发布生效」→ 写 DB published_at + 更新**当前进程**缓存；
- Celery worker / 其它进程在任务入口调用 `refresh_published_agent_prompts(db)`
  拉取已发布模板，保证跨进程一致（DB 为权威）；
- 「恢复默认」→ 清 published_at + 移除缓存，回落代码内置默认。

线程安全：API 进程与 worker 进程各自持有模块级缓存；dict 读写为 GIL 原子操作，
发布/恢复与读取并发场景下最终一致即可，不要求强一致。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.studio import PromptTemplate
from app.models.types import PromptCategory

# agent_key -> 模板分类。agent_key 同时是各 Agent 子类声明的类属性。
AGENT_KEY_TO_CATEGORY: dict[str, PromptCategory] = {
    "script_division": PromptCategory.agent_script_division,
    "element_extract": PromptCategory.agent_element_extract,
    "character_portrait": PromptCategory.agent_character_portrait,
    "scene_info": PromptCategory.agent_scene_info,
    "prop_info": PromptCategory.agent_prop_info,
    "costume_info": PromptCategory.agent_costume_info,
    "consistency_check": PromptCategory.agent_consistency_check,
    "entity_merge": PromptCategory.agent_entity_merge,
    "script_optimize": PromptCategory.agent_script_optimize,
    "script_simplify": PromptCategory.agent_script_simplify,
    "variant_analyze": PromptCategory.agent_variant_analyze,
    "h3_video": PromptCategory.agent_h3_video,
}

_CATEGORY_TO_AGENT_KEY: dict[PromptCategory, str] = {
    category: key for key, category in AGENT_KEY_TO_CATEGORY.items()
}

# agent_key -> 已发布提示词内容。不存在该键 = 未发布，回落代码默认。
_cache: dict[str, str] = {}

# 刷新 TTL：worker 每次任务都会尝试刷新，TTL 内跳过 DB 查询，避免高频任务反复全量拉取。
# 发布/恢复默认走 publish/reset 直接精确更新本进程缓存，不受 TTL 延迟；
# 跨进程（其他 worker/API 实例）最长在 TTL 内感知发布变更。
_CACHE_TTL_SECONDS = 10.0
_last_refresh_monotonic = 0.0


def _refresh_due() -> bool:
    """是否需要重新拉取：缓存为空（首次）或距上次刷新超过 TTL。"""
    return (not _cache) or (time.monotonic() - _last_refresh_monotonic) >= _CACHE_TTL_SECONDS


def get_agent_prompt(agent_key: str) -> str | None:
    """返回已发布的提示词；未发布返回 None（调用方回落代码默认）。"""
    return _cache.get(agent_key)


def _reload_from_rows(rows: list[PromptTemplate]) -> None:
    """把已发布模板行重建进缓存，并刷新计时。"""
    fresh: dict[str, str] = {}
    for row in rows:
        key = _agent_key_of(row)
        if key is not None:
            fresh[key] = row.content
    _cache.clear()
    _cache.update(fresh)
    global _last_refresh_monotonic
    _last_refresh_monotonic = time.monotonic()


def _template_category(template: PromptTemplate) -> PromptCategory | None:
    """仅识别 agent_* 分类的模板；其它分类返回 None。"""
    try:
        category = PromptCategory(template.category)
    except ValueError:
        return None
    return category if category in _CATEGORY_TO_AGENT_KEY else None


def _agent_key_of(template: PromptTemplate) -> str | None:
    category = _template_category(template)
    if category is None:
        return None
    return _CATEGORY_TO_AGENT_KEY[category]


def refresh_published_agent_prompts_sync(db: Session, *, force: bool = False) -> None:
    """同步版刷新：供 Celery worker（同步 Session）在任务入口调用。

    TTL 内且非 force 时跳过 DB 查询（直接使用本进程缓存）。
    """
    if not force and not _refresh_due():
        return
    rows = (
        db.execute(select(PromptTemplate).where(PromptTemplate.published_at.is_not(None)))
        .scalars()
        .all()
    )
    _reload_from_rows(list(rows))


async def refresh_published_agent_prompts(db: AsyncSession, *, force: bool = False) -> None:
    """把 DB 中已发布（published_at 非空）的 agent 模板拉入本进程缓存。

    供 worker / 其它进程在任务入口调用；幂等，可重复执行。
    TTL 内且非 force 时跳过 DB 查询。
    """
    if not force and not _refresh_due():
        return
    stmt = select(PromptTemplate).where(PromptTemplate.published_at.is_not(None))
    rows = (await db.execute(stmt)).scalars().all()
    _reload_from_rows(list(rows))


async def publish_agent_prompt(db: AsyncSession, template_id: str) -> PromptTemplate:
    """发布单条 agent 模板：写 DB（published_at）并更新本进程缓存。"""
    template = await db.get(PromptTemplate, template_id)
    if template is None:
        raise LookupError(f"PromptTemplate {template_id} not found")
    if _agent_key_of(template) is None:
        raise ValueError(f"Template {template_id} is not an agent prompt category")
    template.published_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(template)
    _cache[_agent_key_of(template)] = template.content
    return template


async def reset_agent_prompt(db: AsyncSession, template_id: str) -> PromptTemplate:
    """恢复默认：清 DB（published_at=NULL）并移除缓存，回落代码内置提示词。"""
    template = await db.get(PromptTemplate, template_id)
    if template is None:
        raise LookupError(f"PromptTemplate {template_id} not found")
    if _agent_key_of(template) is None:
        raise ValueError(f"Template {template_id} is not an agent prompt category")
    template.published_at = None
    await db.flush()
    await db.refresh(template)
    _cache.pop(_agent_key_of(template), None)
    return template
