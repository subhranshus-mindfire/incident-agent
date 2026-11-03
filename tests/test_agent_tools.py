from app.llms.agent import get_service_dependencies
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
