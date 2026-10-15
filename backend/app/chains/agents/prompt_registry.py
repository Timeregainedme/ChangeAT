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

from sqlalchemy import select, update
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
#
# 注意：TTL 判据必须用独立的首刷标记，不能用「缓存是否为空」：
# 全部模板都「恢复默认」时 _reload_from_rows 会把缓存清空，若用缓存空当首次判据，
# 则每个任务入口都会判为「需要刷新」→ TTL 形同失效，每次都查库（评审 C-4）。
_CACHE_TTL_SECONDS = 10.0
_last_refresh_monotonic = 0.0
# 本进程是否已经成功拉取过一次（无论结果是否为空）。
_loaded_once = False


def _refresh_due() -> bool:
    """是否需要重新拉取：本进程尚未加载过（首次）或距上次刷新超过 TTL。

    首次判据用 `_loaded_once` 而非 `not _cache`：见上方 C-4 说明。
    """
    return (not _loaded_once) or (time.monotonic() - _last_refresh_monotonic) >= _CACHE_TTL_SECONDS


def _published_order_by():
    """已发布模板的确定性读取顺序。

    同一 category 若存在多行已发布（历史脏数据/直接改库），后写入 `fresh[key]`
    的会覆盖前者，因此顺序决定最终生效内容。这里按 `published_at ASC, id DESC`
    排序：最新发布的行排在最后 → 最终生效；`id` 作为同秒并列时的稳定 tiebreaker
    （评审 C-5）。正常路径下 publish 会清空同分类其它行的 published_at，
    所以该顺序只是兜底。
    """
    return (PromptTemplate.published_at.asc(), PromptTemplate.id.desc())


def get_agent_prompt(agent_key: str) -> str | None:
    """返回已发布的提示词；未发布返回 None（调用方回落代码默认）。"""
    return _cache.get(agent_key)


def _reload_from_rows(rows: list[PromptTemplate]) -> None:
    """把已发布模板行重建进缓存，并刷新计时。

    `rows` 必须已按 `_published_order_by()` 排序（后写入者覆盖前者 = 最终生效）。
    """
    fresh: dict[str, str] = {}
    for row in rows:
        key = _agent_key_of(row)
        if key is not None:
            fresh[key] = row.content
    _cache.clear()
    _cache.update(fresh)
    global _last_refresh_monotonic, _loaded_once
    _last_refresh_monotonic = time.monotonic()
    _loaded_once = True


def _template_category(template: PromptTemplate) -> PromptCategory | None:
    """仅识别 agent_* 分类的模板；其它分类返回 None。

    兼容两种取值形态：ORM 读回可能是 `PromptCategory` 枚举（真实 DB + 类型标注），
    也可能是裸字符串（库中存在枚举外历史值时 / 测试替身）。因此先取 `.value`
    再转换，避免对枚举外历史值抛 ValueError（评审 D-3 的安全取值口径）。
    """
    raw = getattr(template.category, "value", template.category)
    try:
        category = PromptCategory(raw)
    except ValueError:
        return None
    return category if category in _CATEGORY_TO_AGENT_KEY else None


def _agent_key_of(template: PromptTemplate) -> str | None:
    category = _template_category(template)
    if category is None:
        return None
    return _CATEGORY_TO_AGENT_KEY[category]


def _clear_other_published_stmt(category: PromptCategory, exclude_id: str):  # noqa: ANN202
    """构造「清空同分类其它行 published_at」的 UPDATE 语句（不执行）。

    目的：`prompt_templates.category` 无唯一约束，同一分类可能有多行；
    若两行同时 published，刷新时谁生效取决于驱动返回顺序（评审 C-5）。
    发布时把同分类其它行置为未发布，保证「同分类至多一条已发布」。
    """
    return (
        update(PromptTemplate)
        .where(
            PromptTemplate.category == category,
            PromptTemplate.published_at.is_not(None),
            PromptTemplate.id != exclude_id,
        )
        .values(published_at=None)
    )


def _assert_content_not_blank(content: str | None) -> None:
    """拒绝空 / 纯空白内容。

    模板内容为空时 `AgentBase.render_prompt` 会跳过系统提示词
    （`sys = (self.system_prompt or "").strip(); if not sys: return user_prompt`），
    导致 agent 静默失去系统提示词，所以必须在写入边界拦住（评审 B-3）。
    """
    if content is None or not content.strip():
        raise ValueError("提示词内容不能为空")


def refresh_published_agent_prompts_sync(db: Session, *, force: bool = False) -> None:
    """同步版刷新：供 Celery worker（同步 Session）在任务入口调用。

    TTL 内且非 force 时跳过 DB 查询（直接使用本进程缓存）。
    """
    if not force and not _refresh_due():
        return
    stmt = (
        select(PromptTemplate)
        .where(PromptTemplate.published_at.is_not(None))
        .order_by(*_published_order_by())
    )
    rows = db.execute(stmt).scalars().all()
    _reload_from_rows(list(rows))


async def refresh_published_agent_prompts(db: AsyncSession, *, force: bool = False) -> None:
    """把 DB 中已发布（published_at 非空）的 agent 模板拉入本进程缓存。

    供 worker / 其它进程在任务入口调用；幂等，可重复执行。
    TTL 内且非 force 时跳过 DB 查询。
    """
    if not force and not _refresh_due():
        return
    stmt = (
        select(PromptTemplate)
        .where(PromptTemplate.published_at.is_not(None))
        .order_by(*_published_order_by())
    )
    rows = (await db.execute(stmt)).scalars().all()
    _reload_from_rows(list(rows))


async def publish_agent_prompt(db: AsyncSession, template_id: str) -> PromptTemplate:
    """发布单条 agent 模板：写 DB（published_at）并更新本进程缓存。

    - 空 / 纯空白内容直接拒绝（否则运行时会静默无系统提示词，评审 B-3）；
    - 先清空同分类其它行的 published_at，保证同分类至多一条已发布（评审 C-5）。
    """
    template = await db.get(PromptTemplate, template_id)
    if template is None:
        raise LookupError(f"PromptTemplate {template_id} not found")
    agent_key = _agent_key_of(template)
    if agent_key is None:
        raise ValueError(f"Template {template_id} is not an agent prompt category")
    _assert_content_not_blank(template.content)
    category = _template_category(template)
    if category is not None:
        await db.execute(_clear_other_published_stmt(category, template_id))
    template.published_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(template)
    _cache[agent_key] = template.content
    return template


async def update_agent_prompt_content(
    db: AsyncSession,
    template: PromptTemplate,
    content: str,
) -> bool:
    """承载 agent 模板的「内容变更即失效」规则，返回内容是否发生变化。

    「发布才生效」的承诺要求：已发布模板一旦改动内容，必须重新点「发布生效」。
    因此这里把 published_at 置空并清掉落在本进程缓存里的旧内容（评审 B-3）。
    未发布的模板只改内容，不涉及 published_at。
    """
    _assert_content_not_blank(content)
    if template.content == content:
        return False
    template.content = content
    was_published = template.published_at is not None
    if was_published:
        template.published_at = None
        agent_key = _agent_key_of(template)
        if agent_key is not None:
            _cache.pop(agent_key, None)
    return was_published


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
