from unittest.mock import AsyncMock, MagicMock, patch

from app.agents import nodes
from app.constants.enums import IncidentStatus
from app.schemas.agent_state import ApprovalStatus


async def test_downstream_evidence_survives_the_next_correlation() -> None:
    log = MagicMock(sample_line="downstream timeout", count=3)
    state = {
        "service": "payment-api",
        "affected_services": ["payment-api", "order-service"],
        "retry_count": 0,
        "evidence": [],
        "downstream_evidence": [],
        "metrics": None,
        "log_findings": [],
        "log_signatures": [],
        "deployments": [],
        "retrieved_incidents": [],
    }

    with patch.object(nodes, "fetch_application_logs", AsyncMock(return_value=[log])):
        expanded = await nodes.node_expand_diagnostics(state)
    state = {**state, **expanded}

    correlated = await nodes.node_correlate_evidence(state)

    assert any("downstream timeout" in item for item in correlated["evidence"])


async def test_failed_remediation_call_is_recorded_not_raised() -> None:
    proposal = MagicMock(action_type=MagicMock(value="restart_service"))
    state = {
        "pending_action": proposal,
        "remediation_proposal": proposal,
        "approval_status": ApprovalStatus.APPROVED,
        "service": "order-service",
        "incident_id": "inc-test-1",
        "executed_actions": [],
        "audit_events": [],
    }

    with patch.object(nodes, "execute_remediation", AsyncMock(side_effect=RuntimeError("boom"))):
        update = await nodes.node_execute_remediation(state)

    assert update["execution_result"].success is False
    assert "boom" in update["execution_result"].message
    assert update["status"] == IncidentStatus.INVESTIGATING
