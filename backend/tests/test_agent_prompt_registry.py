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
    """每个用例前清空缓存，避免跨用例污染。"""
    prompt_registry._cache.clear()
    yield
    prompt_registry._cache.clear()


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
    """发布精确更新单条缓存，不推进全局刷新计时（其余条目仍按 TTL 轮询）。"""
    published = _template(template_id="tpl-a", content="旧内容", published_at=datetime.now(UTC))
    db = _CountingDB([published])
    await refresh_published_agent_prompts(db)
    count_before = db.execute_count

    draft = _template(template_id="tpl-b", category=PromptCategory.agent_element_extract, content="草稿")
    db.by_id["tpl-b"] = draft
    await publish_agent_prompt(db, "tpl-b")

    # 发布只写缓存单条，不触发全量拉取
    assert db.execute_count == count_before
    assert get_agent_prompt("script_division") == "旧内容"
    assert get_agent_prompt("element_extract") == "草稿"


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
