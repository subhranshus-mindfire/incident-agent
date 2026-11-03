import httpx
import pytest
from groq import BadRequestError
from langchain_core.messages import AIMessage

from app.llms.agent import _invoke_model, get_service_dependencies
from app.tools.investigation_tools import get_service_dependencies as dependency_map


async def test_agent_dependency_tool_returns_known_map() -> None:
    result = await get_service_dependencies.ainvoke({"service": "payment-api"})
    assert result["known"] is True
    assert result["upstream_services"] == ["order-service", "checkout-web"]
    assert result["downstream_services"] == ["postgres", "auth-service", "redis"]


async def test_agent_dependency_tool_reports_unknown_service() -> None:
    result = await get_service_dependencies.ainvoke({"service": "made-up-service"})
    assert result["known"] is False
    assert "error" in result


def test_unknown_service_gets_empty_dependencies_not_invented_ones() -> None:
    mapping = dependency_map("made-up-service")
    assert mapping.upstream_services == []
    assert mapping.downstream_services == []


class _FlakyModel:
    """Rejects the first call the way the provider does for an unknown tool name, then answers."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def ainvoke(self, messages: list[object]) -> AIMessage:
        self.calls += 1
        if self.calls <= self.failures:
            response = httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com"))
            raise BadRequestError(
                "tool call validation failed: attempted to call tool 'service_name'",
                response=response,
                body=None,
            )
        return AIMessage(content="ok")


async def test_model_call_retries_when_it_names_an_unknown_tool() -> None:
    model = _FlakyModel(failures=1)
    result = await _invoke_model(model, [])
    assert result.content == "ok"
    assert model.calls == 2


async def test_model_call_gives_up_after_repeated_unknown_tool_names() -> None:
    model = _FlakyModel(failures=10)
    with pytest.raises(BadRequestError):
        await _invoke_model(model, [])
    assert model.calls == 3


def test_message_text_reads_plain_and_block_content() -> None:
    from app.llms.agent import _message_text

    assert _message_text(AIMessage(content="plain")) == "plain"
    blocks = AIMessage(
        content=[{"type": "text", "text": "Hello "}, {"type": "text", "text": "world"}]
    )
    assert _message_text(blocks) == "Hello world"
