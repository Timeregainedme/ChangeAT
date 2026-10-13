"""Script processing agents parsing regression tests."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from app.chains.agents import ConsistencyCheckerAgent, ScriptDividerAgent
from app.schemas.skills.script_processing import ScriptConsistencyCheckResult


class _MockChatModel(BaseChatModel):
    def __init__(self, response: str) -> None:
        super().__init__()
        self._response = response

    @property
    def _llm_type(self) -> str:  # pragma: no cover
        return "mock-chat-model"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # type: ignore[override]
        msg = AIMessage(content=self._response)
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _checker() -> ConsistencyCheckerAgent:
    return ConsistencyCheckerAgent(_MockChatModel('{"issues": [], "has_issues": false, "summary": null}'))


def test_consistency_format_output_accepts_unquoted_keys() -> None:
    agent = _checker()
    raw = "{issues: [], has_issues: false, summary: null}"

    result = agent.format_output(raw)

    assert isinstance(result, ScriptConsistencyCheckResult)
    assert result.has_issues is False
    assert result.issues == []


def test_consistency_format_output_accepts_python_literal_style() -> None:
    agent = _checker()
    raw = "{'issues': [], 'has_issues': False, 'summary': None}"

    result = agent.format_output(raw)

    assert isinstance(result, ScriptConsistencyCheckResult)
    assert result.has_issues is False
    assert result.summary is None


def test_consistency_format_output_accepts_model_call_style() -> None:
    agent = _checker()
    raw = "ScriptConsistencyCheckResult(issues=[], has_issues=False, summary=None)"

    result = agent.format_output(raw)

    assert isinstance(result, ScriptConsistencyCheckResult)
    assert result.has_issues is False
    assert result.issues == []


def test_agent_keeps_injected_model_instance_without_rebinding() -> None:
    """Agent 构造必须原样保留注入的模型实例。

    回归护栏：`base.py` 曾写 `self._model.bind(extra_body={"enable_thinking": ...})` 并丢弃返回值
    （无效代码）。若改成 `self._model = self._model.bind(...)`，`_model` 会变成 RunnableBinding，
    且会用百炼专有的 `enable_thinking` 覆盖 DeepSeek 的 `thinking` 字段。
    """
    llm = ChatOpenAI(
        model="deepseek-flash",
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        extra_body={"thinking": {"type": "disabled"}},
    )
    agent = ConsistencyCheckerAgent(llm)

    assert agent._model is llm
    assert llm.extra_body == {"thinking": {"type": "disabled"}}


def test_agent_enable_thinking_is_declarative_and_host_selected() -> None:
    """`enable_thinking` 是声明式契约：宿主负责按它选择模型构造方式。

    见 `app/dependencies.py` 的 `get_llm`（thinking=True）/ `get_nothinking_llm`（thinking=False），
    以及 `script_processing.py:150` 用 `get_nothinking_llm` 构造 `ScriptDividerAgent`。
    """
    from app.chains.agents.base import AgentBase  # noqa: PLC0415

    assert AgentBase.enable_thinking is True
    assert ScriptDividerAgent.enable_thinking is False


