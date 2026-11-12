import pytest

from app.agents.approval_policy import needs_human_approval
from app.constants.enums import IncidentSeverity
from app.schemas.agent_state import ApprovalStatus, RiskTier


@pytest.mark.parametrize("risk", [RiskTier.LOW, RiskTier.MEDIUM])
def test_medium_severity_low_or_medium_risk_runs_without_a_person(risk: RiskTier) -> None:
    assert needs_human_approval(risk, IncidentSeverity.MEDIUM) is False


@pytest.mark.parametrize("risk", [RiskTier.HIGH, RiskTier.CRITICAL])
def test_high_risk_always_waits_for_a_person(risk: RiskTier) -> None:
    for severity in IncidentSeverity:
        assert needs_human_approval(risk, severity) is True


@pytest.mark.parametrize(
    "severity", [IncidentSeverity.HIGH, IncidentSeverity.CRITICAL, IncidentSeverity.LOW]
)
def test_other_severities_still_wait_for_a_person(severity: IncidentSeverity) -> None:
    assert needs_human_approval(RiskTier.LOW, severity) is True
    assert needs_human_approval(RiskTier.MEDIUM, severity) is True


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (IncidentSeverity.MEDIUM, ApprovalStatus.AUTO_APPROVED),
        (IncidentSeverity.HIGH, ApprovalStatus.PENDING),
    ],
)
async def test_restart_waits_only_when_severity_is_not_medium(
    monkeypatch: pytest.MonkeyPatch, severity: IncidentSeverity, expected: ApprovalStatus
) -> None:
    from app.agents import nodes
    from app.schemas.agent_state import RCAHypothesis, RemediationActionType

    async def no_live_faults(service: str) -> dict[str, bool]:
        return {}

    monkeypatch.setattr(nodes, "get_active_faults", no_live_faults)
    hypothesis = RCAHypothesis(
        title="Heap leak",
        root_cause="Memory is climbing.",
        confidence_score=0.8,
        evidence_citations=[],
        recommended_action=RemediationActionType.ROLLING_RESTART,
    )
    state = {
        "incident_id": "inc-policy",
        "service": "payment-api",
        "severity": severity,
        "selected_hypothesis": hypothesis,
    }

    update = await nodes.node_assess_blast_radius(state)  # type: ignore[arg-type]

    assert update["approval_status"] == expected
    assert update["remediation_proposal"].requires_approval is (expected == ApprovalStatus.PENDING)
