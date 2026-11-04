import pytest

from app.agents import nodes
from app.agents.graph import create_investigation_graph
from app.constants.enums import IncidentSeverity, IncidentStatus
from app.schemas.agent_state import (
    ApprovalStatus,
    RemediationActionType,
    RemediationExecutionResult,
    RemediationProposal,
    RiskTier,
)


def test_telemetry_and_retrieval_fan_out_from_ingest_and_join_at_correlation() -> None:
    graph = create_investigation_graph()
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("ingest_alert", "gather_telemetry") in edges
    assert ("ingest_alert", "retrieve_qdrant") in edges
    assert ("gather_telemetry", "correlate_evidence") in edges
    assert ("retrieve_qdrant", "correlate_evidence") in edges
    assert ("gather_telemetry", "retrieve_qdrant") not in edges


async def test_retrieval_query_does_not_depend_on_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def fake_search(query: str, service: str | None = None, limit: int = 3) -> list[object]:
        seen.append(query)
        return []

    class NoRunbooks:
        async def search_runbooks(self, **kwargs: object) -> list[object]:
            return []

    monkeypatch.setattr(nodes, "search_past_incidents", fake_search)
    monkeypatch.setattr(nodes, "get_shared_qdrant_service", lambda: NoRunbooks())
    state = {"service": "payment-api", "symptoms": "HTTP 500 errors", "log_findings": []}
    await nodes.node_retrieve_qdrant(state)  # type: ignore[arg-type]
    assert seen and all(query == "HTTP 500 errors" for query in seen)


async def test_second_execution_of_the_same_action_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_execute(
        action: str, service: str, approval_id: str | None = None, parameters: dict | None = None
    ) -> RemediationExecutionResult:
        calls.append(action)
        return RemediationExecutionResult(success=True, action_type=action, message="applied")

    monkeypatch.setattr(nodes, "execute_remediation", fake_execute)
    proposal = RemediationProposal(
        action_type=RemediationActionType.ROLLBACK_DEPLOYMENT,
        target_resource="deployment/payment-api",
        blast_radius="payment-api",
        rollback_plan="roll forward",
        risk_tier=RiskTier.HIGH,
        requires_approval=True,
    )
    earlier = RemediationExecutionResult(
        success=True, action_type="ROLLBACK_DEPLOYMENT", message="applied earlier"
    )
    state = {
        "incident_id": "inc-dup-1",
        "service": "payment-api",
        "pending_action": proposal,
        "approval_status": ApprovalStatus.APPROVED,
        "executed_actions": [earlier],
        "status": IncidentStatus.INVESTIGATING,
        "severity": IncidentSeverity.HIGH,
    }
    update = await nodes.node_execute_remediation(state)  # type: ignore[arg-type]
    assert calls == []
    assert update["execution_result"] is earlier
    assert any("Duplicate skipped" in event for event in update["audit_events"])
