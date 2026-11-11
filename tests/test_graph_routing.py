from app.agents.graph import route_after_blast_radius
from app.rca.engine import SREInvestigationEngine
from app.schemas.agent_state import ApprovalStatus


def test_no_proposal_skips_approval_gate() -> None:
    state = {"remediation_proposal": None, "approval_status": ApprovalStatus.PENDING}

    assert route_after_blast_radius(state) == "generate_postmortem"


def test_pending_proposal_waits_for_approval() -> None:
    state = {"remediation_proposal": object(), "approval_status": ApprovalStatus.PENDING}

    assert route_after_blast_radius(state) == "await_approval"


def test_auto_approved_proposal_executes_directly() -> None:
    state = {"remediation_proposal": object(), "approval_status": ApprovalStatus.AUTO_APPROVED}

    assert route_after_blast_radius(state) == "execute_remediation"


def test_postmortem_accepts_status_restored_as_plain_string() -> None:
    # The Postgres checkpointer returns top-level StrEnum fields as plain strings.
    state = {
        "incident_id": "inc-test",
        "service": "payment-api",
        "severity": "critical",
        "status": "resolved",
        "symptoms": "errors",
        "selected_hypothesis": None,
        "remediation_proposal": None,
        "execution_result": None,
        "verification_report": None,
        "audit_events": [],
    }

    report = SREInvestigationEngine().generate_postmortem_report(state)

    assert "**Status:** `RESOLVED`" in report.markdown_content


def test_postmortem_is_not_resolved_or_templated_when_health_is_unverified() -> None:
    from app.constants.enums import IncidentStatus
    from app.rca.engine import SREInvestigationEngine
    from app.schemas.agent_state import (
        HealthVerificationReport,
        RemediationActionType,
        RemediationExecutionResult,
        RemediationProposal,
        RiskTier,
    )

    proposal = RemediationProposal(
        action_type=RemediationActionType.ROLLING_RESTART,
        target_resource="deployment/payment-api",
        parameters={},
        risk_tier=RiskTier.MEDIUM,
        blast_radius="Restart",
        rollback_plan="None",
        requires_approval=True,
    )
    verif = HealthVerificationReport(
        stabilized=False,
        previous_error_rate=99.0,
        current_error_rate=0.0,
        previous_latency_ms=2325.0,
        current_latency_ms=0.0,
        observation_window_seconds=60,
        details="Metrics not collected (p95_latency_ms), so health cannot be verified.",
    )
    state = {
        "incident_id": "inc-test",
        "service": "payment-api",
        "severity": "medium",
        "status": IncidentStatus.INVESTIGATING,
        "symptoms": "errors",
        "selected_hypothesis": None,
        "remediation_proposal": proposal,
        "execution_result": RemediationExecutionResult(
            success=True, action_type="ROLLING_RESTART", message="applied"
        ),
        "verification_report": verif,
        "audit_events": [],
    }

    report = SREInvestigationEngine().generate_postmortem_report(state)

    assert "**Status:** `INVESTIGATING`" in report.markdown_content
    assert "Not verified." in report.markdown_content
    assert "Implement tighter alert thresholds" not in report.markdown_content
    assert "Re-check service health once traffic resumes" in report.prevention_action_items
