"""Agent 提示词注册表测试：发布/恢复默认/刷新缓存/AgentBase 覆盖回落。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.chains.agents import prompt_registry
from app.chains.agents.base import AgentBase
from app.chains.agents.prompt_registry import (
    AGENT_KEY_TO_CATEGORY,
    get_agent_prompt,
    publish_agent_prompt,
    refresh_published_agent_prompts,
    reset_agent_prompt,
)
from app.dependencies import get_db
from app.models.studio import PromptTemplate
from app.models.types import PromptCategory


def _template(
    *,
    template_id: str = "tpl-1",
    category: PromptCategory = PromptCategory.agent_script_division,
    content: str = "发布后的提示词",
    published_at: datetime | None = None,
) -> PromptTemplate:
    now = datetime.now(UTC)
    return PromptTemplate(
        id=template_id,
        category=category,
        name="测试模板",
        preview="",
        content=content,
        variables=[],
        is_default=False,
        is_system=False,
        published_at=published_at,
        created_at=now,
        updated_at=now,
    )


class _FakeScalars:
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
    """最小 DB 替身：覆盖 registry 用到的 get/execute/flush/refresh/commit。"""

    def __init__(self, templates: list[PromptTemplate]) -> None:
        self.by_id = {t.id: t for t in templates}

    async def get(self, model: type, entity_id: str):  # noqa: ANN001
        return self.by_id.get(entity_id)

    async def execute(self, *_args, **_kwargs):  # noqa: ANN001
        published = [t for t in self.by_id.values() if t.published_at is not None]
        return _FakeExecuteResult(published)

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def delete(self, obj: PromptTemplate) -> None:
        self.by_id.pop(obj.id, None)


@pytest.fixture(autouse=True)
def _clear_registry_cache() -> None:
    """每个用例前后重置注册表进程内状态，避免跨用例污染。

    除了 `_cache`，还要复位首刷标记 `_loaded_once` 与刷新计时：否则前一个用例
    已经「加载过一次」，后一个用例的首次刷新会被 TTL 直接跳过（评审 C-4 引入
    的标记位必须能被测试隔离）。
    """
    prompt_registry._cache.clear()
    prompt_registry._loaded_once = False
    prompt_registry._last_refresh_monotonic = 0.0
    yield
    prompt_registry._cache.clear()
    prompt_registry._loaded_once = False
    prompt_registry._last_refresh_monotonic = 0.0


@pytest.mark.asyncio
async def test_publish_updates_db_and_cache() -> None:
    """发布：published_at 置为当前时间，缓存写入用户编辑内容。"""
    template = _template(content="用户编辑的新提示词")
    db = _FakeDB([template])

    await publish_agent_prompt(db, "tpl-1")

    assert template.published_at is not None
    assert get_agent_prompt("script_division") == "用户编辑的新提示词"


@pytest.mark.asyncio
async def test_reset_clears_db_and_cache() -> None:
    """恢复默认：published_at 清空，缓存移除，回落代码默认。"""
    template = _template(content="已发布内容", published_at=datetime.now(UTC))
    db = _FakeDB([template])
    prompt_registry._cache["script_division"] = "已发布内容"

    await reset_agent_prompt(db, "tpl-1")

    assert template.published_at is None
    assert get_agent_prompt("script_division") is None


@pytest.mark.asyncio
async def test_refresh_loads_only_published() -> None:
    """刷新：仅加载 published_at 非空的模板；未发布的不进缓存。"""
    db = _FakeDB(
        [
            _template(template_id="tpl-a", content="已发布A", published_at=datetime.now(UTC)),
            _template(template_id="tpl-b", content="未发布B"),
            _template(
                template_id="tpl-c",
                category=PromptCategory.agent_h3_video,
                content="已发布H3",
                published_at=datetime.now(UTC),
            ),
        ]
    )

    await refresh_published_agent_prompts(db)

    assert get_agent_prompt("script_division") == "已发布A"
    assert get_agent_prompt("h3_video") == "已发布H3"
    # 未发布的不进入缓存
    assert "element_extract" not in prompt_registry._cache


@pytest.mark.asyncio
async def test_publish_rejects_non_agent_category() -> None:
    """非 agent_* 分类的模板不允许发布。"""
    db = _FakeDB([_template(category=PromptCategory.video_prompt)])

    with pytest.raises(ValueError, match="not an agent prompt category"):
        await publish_agent_prompt(db, "tpl-1")


def test_get_agent_prompt_defaults_to_none() -> None:
    """未发布时 get_agent_prompt 返回 None（调用方回落代码默认）。"""
    assert get_agent_prompt("script_division") is None


def test_agent_base_system_prompt_unpublished_falls_back() -> None:
    """未发布：AgentBase.system_prompt 回落代码内置默认。"""

    class _DummyAgent(AgentBase[PromptTemplate]):
        agent_key = "script_division"

        @property
        def prompt_template(self):
            raise NotImplementedError

        @property
        def output_model(self):
            return PromptTemplate

        def _default_system_prompt(self) -> str:
            return "代码内置默认提示词"

    agent = _DummyAgent.__new__(_DummyAgent)
    assert agent.system_prompt == "代码内置默认提示词"


def test_agent_base_system_prompt_uses_published() -> None:
    """已发布：AgentBase.system_prompt 返回用户发布的内容。"""

    class _DummyAgent(AgentBase[PromptTemplate]):
        agent_key = "script_division"

        @property
        def prompt_template(self):
            raise NotImplementedError

        @property
        def output_model(self):
            return PromptTemplate

        def _default_system_prompt(self) -> str:
            return "代码内置默认提示词"

    prompt_registry._cache["script_division"] = "用户发布的内容"
    agent = _DummyAgent.__new__(_DummyAgent)
    assert agent.system_prompt == "用户发布的内容"


def test_agent_key_mapping_covers_all_registry_keys() -> None:
    """AGENT_KEY_TO_CATEGORY 与 12 个 agent_key 一一对应，分类均属 agent_*。"""
    assert len(AGENT_KEY_TO_CATEGORY) == 12
    for category in AGENT_KEY_TO_CATEGORY.values():
        assert category.value.startswith("agent_")


# ---------- TTL 刷新 ----------


class _CountingDB(_FakeDB):
    """记录 execute 调用次数的 DB 替身，用于断言 TTL 跳过。"""

    def __init__(self, templates: list[PromptTemplate]) -> None:
        super().__init__(templates)
        self.execute_count = 0

    async def execute(self, *_args, **_kwargs):  # noqa: ANN001
        self.execute_count += 1
        return await super().execute(*_args, **_kwargs)


@pytest.mark.asyncio
async def test_refresh_skips_db_query_within_ttl() -> None:
    """TTL 窗口内且缓存非空：跳过 DB 查询。"""
    db = _CountingDB([_template(template_id="tpl-a", content="A", published_at=datetime.now(UTC))])
    await refresh_published_agent_prompts(db)
    first_count = db.execute_count
    assert first_count == 1

    # 第二次刷新在 TTL 内：不应再查库
    await refresh_published_agent_prompts(db)

    assert db.execute_count == first_count
    assert get_agent_prompt("script_division") == "A"


@pytest.mark.asyncio
async def test_refresh_force_bypasses_ttl() -> None:
    """force=True：即使 TTL 内也强制拉取 DB。"""
    db = _CountingDB([_template(template_id="tpl-a", content="A", published_at=datetime.now(UTC))])
    await refresh_published_agent_prompts(db)
    await refresh_published_agent_prompts(db, force=True)

    assert db.execute_count == 2


@pytest.mark.asyncio
async def test_publish_does_not_advance_refresh_timer() -> None:
    """发布只精确更新缓存，不推进全局刷新计时（其余条目仍按 TTL 轮询）。

    发布现在会额外执行一条 `UPDATE ... published_at=NULL`（同分类互斥，评审 C-5），
    因此 execute 次数 +1；但**刷新计时不被推进** —— 用下一次刷新是否仍跳过查库来断言。
    """
    published = _template(template_id="tpl-a", content="旧内容", published_at=datetime.now(UTC))
    db = _CountingDB([published])
    await refresh_published_agent_prompts(db)
    count_before = db.execute_count

    draft = _template(template_id="tpl-b", category=PromptCategory.agent_element_extract, content="草稿")
    db.by_id["tpl-b"] = draft
    await publish_agent_prompt(db, "tpl-b")
    count_after_publish = db.execute_count

    # 发布只精确更新缓存单条，不触发全量拉取
    assert count_after_publish == count_before + 1  # 仅新增同分类互斥 UPDATE
    assert get_agent_prompt("script_division") == "旧内容"
    assert get_agent_prompt("element_extract") == "草稿"

    # 发布没有重置刷新计时：下一次刷新仍在 TTL 内，不查库
    await refresh_published_agent_prompts(db)
    assert db.execute_count == count_after_publish


# ---------- 接口层：publish / reset ----------


class _FakeHttpDB(_FakeDB):
    """HTTP 接口测试用的 DB 替身：额外支持 commit（已在基类）与 refresh 后对象更新。"""


def _override_db(db: _FakeHttpDB):
    from collections.abc import AsyncGenerator

    async def _get_db() -> AsyncGenerator[_FakeHttpDB, None]:
        yield db

    return _get_db


def test_publish_endpoint_sets_published_at(client) -> None:
    """POST /prompts/{id}/publish：published_at 非空并返回模板。"""
    from app.main import app

    template = _template(content="用户编辑的新提示词")
    db = _FakeHttpDB([template])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post("/api/v1/studio/prompts/tpl-1/publish")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["published_at"] is not None
        assert body["data"]["content"] == "用户编辑的新提示词"
        assert template.published_at is not None
        assert get_agent_prompt("script_division") == "用户编辑的新提示词"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_reset_endpoint_clears_published_at(client) -> None:
    """POST /prompts/{id}/reset：published_at 清空并回落默认。"""
    from app.main import app

    template = _template(content="已发布内容", published_at=datetime.now(UTC))
    db = _FakeHttpDB([template])
    prompt_registry._cache["script_division"] = "已发布内容"
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post("/api/v1/studio/prompts/tpl-1/reset")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["published_at"] is None
        assert template.published_at is None
        assert get_agent_prompt("script_division") is None
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_publish_endpoint_rejects_non_agent_category(client) -> None:
    """非 agent 分类发布：400。"""
    from app.main import app

    template = _template(category=PromptCategory.video_prompt)
    db = _FakeHttpDB([template])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post("/api/v1/studio/prompts/tpl-1/publish")
        assert response.status_code == 400
        assert "not an agent prompt category" in response.json()["message"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_publish_endpoint_returns_404_for_missing(client) -> None:
    """模板不存在：404。"""
    from app.main import app

    db = _FakeHttpDB([])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post("/api/v1/studio/prompts/missing/publish")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_delete_agent_template_is_forbidden(client) -> None:
    """agent_* 模板禁止删除（可通过编辑/恢复默认调整）。"""
    from app.main import app

    template = _template(category=PromptCategory.agent_script_division)
    db = _FakeHttpDB([template])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/prompts/tpl-1")
        assert response.status_code == 403
        assert "Agent 提示词模板不可删除" in response.json()["message"]
        assert db.by_id["tpl-1"] is not None  # 行未被删除
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_delete_generation_template_still_allowed(client) -> None:
    """非 agent 分类的可编辑模板仍可删除。"""
    from app.main import app

    template = _template(template_id="tpl-gen", category=PromptCategory.combined)
    db = _FakeHttpDB([template])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/prompts/tpl-gen")
        assert response.status_code == 200
        assert "tpl-gen" not in db.by_id  # 行被删除
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------- B-3：内容变更即失效 + 拒绝空内容 ----------


@pytest.mark.asyncio
async def test_update_published_content_invalidates_publication() -> None:
    """已发布模板改内容 → published_at 置空（必须重新点「发布生效」）。"""
    from app.chains.agents.prompt_registry import update_agent_prompt_content

    template = _template(content="旧内容", published_at=datetime.now(UTC))
    prompt_registry._cache["script_division"] = "旧内容"

    changed = await update_agent_prompt_content(None, template, "新内容")  # type: ignore[arg-type]

    assert changed is True
    assert template.content == "新内容"
    assert template.published_at is None  # 发布态被撤销
    assert get_agent_prompt("script_division") is None  # 缓存同步失效


@pytest.mark.asyncio
async def test_update_unpublished_content_keeps_publication_state() -> None:
    """未发布模板改内容：只改内容，不产生发布态。"""
    from app.chains.agents.prompt_registry import update_agent_prompt_content

    template = _template(content="旧草稿")

    changed = await update_agent_prompt_content(None, template, "新草稿")  # type: ignore[arg-type]

    assert changed is False
    assert template.content == "新草稿"
    assert template.published_at is None


@pytest.mark.asyncio
async def test_update_blank_content_is_rejected() -> None:
    """空白内容必须拒绝：否则 AgentBase 会静默失去系统提示词。"""
    from app.chains.agents.prompt_registry import update_agent_prompt_content

    template = _template(content="旧内容")

    with pytest.raises(ValueError, match="提示词内容不能为空"):
        await update_agent_prompt_content(None, template, "   \n  ")  # type: ignore[arg-type]

    assert template.content == "旧内容"  # 原内容未被破坏


@pytest.mark.asyncio
async def test_publish_blank_content_is_rejected() -> None:
    """发布空白内容必须拒绝（发布是运行时的最后一道闸）。"""
    template = _template(content="   ")
    db = _FakeDB([template])

    with pytest.raises(ValueError, match="提示词内容不能为空"):
        await publish_agent_prompt(db, "tpl-1")

    assert template.published_at is None
    assert get_agent_prompt("script_division") is None


def test_patch_endpoint_invalidates_published_template(client) -> None:
    """PATCH 接口：已发布模板改内容后 published_at 变为 null。"""
    from app.main import app

    template = _template(content="旧内容", published_at=datetime.now(UTC))
    db = _FakeHttpDB([template])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.patch("/api/v1/studio/prompts/tpl-1", json={"content": "新内容"})
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["content"] == "新内容"
        assert body["data"]["published_at"] is None
        assert template.published_at is None
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_patch_endpoint_rejects_blank_content(client) -> None:
    """PATCH 接口：空白内容返回 400，且不改动原内容。"""
    from app.main import app

    template = _template(content="旧内容")
    db = _FakeHttpDB([template])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.patch("/api/v1/studio/prompts/tpl-1", json={"content": "   "})
        assert response.status_code == 400
        assert "提示词内容不能为空" in response.json()["message"]
        assert template.content == "旧内容"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_publish_endpoint_rejects_blank_content(client) -> None:
    """POST publish：空白内容返回 400。"""
    from app.main import app

    template = _template(content="\n\t ")
    db = _FakeHttpDB([template])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.post("/api/v1/studio/prompts/tpl-1/publish")
        assert response.status_code == 400
        assert "提示词内容不能为空" in response.json()["message"]
        assert template.published_at is None
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------- C-4：首刷标记 ----------


@pytest.mark.asyncio
async def test_ttl_holds_when_no_published_rows() -> None:
    """全部「恢复默认」（无已发布行）时，TTL 仍必须生效。

    回归 C-4：旧实现用 `not _cache` 当首刷判据，而全恢复默认会把缓存清空
    → 每个任务入口都判定为「需要刷新」，TTL 形同失效。
    """
    db = _CountingDB([_template(template_id="tpl-a", content="A")])

    await refresh_published_agent_prompts(db)
    assert db.execute_count == 1
    assert prompt_registry._cache == {}

    await refresh_published_agent_prompts(db)

    assert db.execute_count == 1  # TTL 内不再查库
    assert get_agent_prompt("script_division") is None


@pytest.mark.asyncio
async def test_refresh_runs_again_after_publish_state_changes() -> None:
    """发布态变化后（新一轮任务）必须重新拉取。"""
    template = _template(template_id="tpl-a", content="A")
    db = _CountingDB([template])

    await refresh_published_agent_prompts(db)
    template.published_at = datetime.now(UTC)
    await refresh_published_agent_prompts(db, force=True)

    assert db.execute_count == 2
    assert get_agent_prompt("script_division") == "A"


# ---------- C-5：同分类唯一已发布 + 确定性排序 ----------


def _capture_execute(db: _FakeDB, sink: list) -> None:
    """把 execute 收到的语句记进 sink（供断言 SQL 语义）。"""

    async def _execute(statement, *args, **kwargs):  # noqa: ANN001
        sink.append(statement)
        return await _FakeDB.execute(db, statement, *args, **kwargs)

    db.execute = _execute  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_publish_clears_other_published_rows_in_same_category() -> None:
    """发布时先清空同分类其它行的 published_at（保证同分类至多一条已发布）。"""
    keep = _template(template_id="tpl-old", content="旧发布", published_at=datetime.now(UTC))
    target = _template(template_id="tpl-new", content="新发布")
    db = _FakeDB([keep, target])
    statements: list = []
    _capture_execute(db, statements)

    await publish_agent_prompt(db, "tpl-new")

    assert len(statements) == 1
    compiled = str(statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE prompt_templates SET published_at" in compiled
    assert "published_at IS NOT NULL" in compiled
    # 只排除「正在发布的这一行」：同分类其它行（无论 id 是什么）都被清空
    assert "prompt_templates.id != 'tpl-new'" in compiled
    assert "'agent_script_division'" in compiled


@pytest.mark.asyncio
async def test_refresh_query_has_deterministic_order() -> None:
    """刷新查询必须带确定性 ORDER BY（同分类多行时结果不能取决于驱动顺序）。"""
    db = _FakeDB([_template(template_id="tpl-a", content="A", published_at=datetime.now(UTC))])
    statements: list = []
    _capture_execute(db, statements)

    await refresh_published_agent_prompts(db)

    assert len(statements) == 1
    compiled = str(statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "ORDER BY prompt_templates.published_at ASC, prompt_templates.id DESC" in compiled


@pytest.mark.asyncio
async def test_refresh_last_row_wins_under_same_category() -> None:
    """同分类多行已发布（历史脏数据）时，排序中最后一行生效。"""
    older = _template(template_id="tpl-a", content="较早已发布", published_at=datetime(2024, 1, 1, tzinfo=UTC))
    newer = _template(template_id="tpl-b", content="最新已发布", published_at=datetime(2024, 6, 1, tzinfo=UTC))
    db = _FakeDB([older, newer])

    await refresh_published_agent_prompts(db)

    assert get_agent_prompt("script_division") == "最新已发布"


# ---------- D-3：枚举外历史 category 不得导致删除接口 400 ----------


def test_delete_unmapped_category_does_not_regress(client) -> None:
    """库中存在枚举外的历史 category 时，删除路径不得抛 ValueError 返 400。"""
    from app.main import app

    template = _template(template_id="tpl-legacy", category="legacy_custom_prompt")  # type: ignore[arg-type]
    db = _FakeHttpDB([template])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/prompts/tpl-legacy")
        assert response.status_code == 200
        assert "tpl-legacy" not in db.by_id
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_delete_unmapped_agent_like_category_matches_safely(client) -> None:
    """枚举外但以 agent_ 开头的历史值：按值判断后仍拒绝删除（403 而非 500/400）。"""
    from app.main import app

    template = _template(template_id="tpl-legacy-agent", category="agent_legacy_unknown")  # type: ignore[arg-type]
    db = _FakeHttpDB([template])
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/prompts/tpl-legacy-agent")
        assert response.status_code == 403
        assert "tpl-legacy-agent" in db.by_id
    finally:
        app.dependency_overrides.pop(get_db, None)
