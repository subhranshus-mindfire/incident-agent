from app.agents.graph import route_after_blast_radius
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
