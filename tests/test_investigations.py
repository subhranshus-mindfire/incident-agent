import httpx
import pytest

from app.constants.enums import IncidentSeverity, IncidentStatus
from app.llms.llm_engine import SREInvestigationEngine
from app.schemas.agent_state import (
    ApprovalStatus,
    LogSignature,
    RCAHypothesis,
    RemediationActionType,
    RemediationProposal,
    RiskTier,
    TelemetrySummary,
)
from app.services.investigation_service import InvestigationService
from app.services.remediation_service import RemediationExecutor


@pytest.fixture
def engine() -> SREInvestigationEngine:
    return SREInvestigationEngine()


@pytest.fixture
def executor() -> RemediationExecutor:
    return RemediationExecutor()


@pytest.fixture
def investigation_service() -> InvestigationService:
    return InvestigationService()


def test_rca_hypotheses_generation(engine: SREInvestigationEngine):
    # 1. CPU Saturated telemetry
    telemetry_cpu = TelemetrySummary(
        cpu_usage_pct=92.0, memory_usage_pct=45.0, http_error_rate_pct=1.0
    )
    hypotheses = engine.formulate_rca_hypotheses(
        service="payment-service",
        symptoms="High CPU utilization and latency spike",
        telemetry=telemetry_cpu,
        logs=[],
        runbooks=[],
    )
    assert len(hypotheses) > 0
    top = hypotheses[0]
    assert "Compute Saturation" in top.title
    assert top.confidence_score >= 0.90
    assert top.recommended_action == RemediationActionType.SCALE_UP_REPLICAS

    # 2. Database deadlock in logs
    logs_db = [
        LogSignature(sample_line="ERROR: connection pool timeout waiting for connection", count=15)
    ]
    hypotheses_db = engine.formulate_rca_hypotheses(
        service="postgres",
        symptoms="Transactions timing out",
        telemetry=None,
        logs=logs_db,
        runbooks=[],
    )
    assert len(hypotheses_db) > 0
    top_db = hypotheses_db[0]
    assert "Database Connection Pool" in top_db.title
    assert top_db.recommended_action == RemediationActionType.TERMINATE_DB_TRANSACTIONS


def test_blast_radius_evaluation(engine: SREInvestigationEngine):
    # Low risk action: stateless replica scaling
    hypo_scale = RCAHypothesis(
        title="High CPU",
        root_cause="CPU spike",
        confidence_score=0.9,
        recommended_action=RemediationActionType.SCALE_UP_REPLICAS,
    )
    proposal_scale = engine.evaluate_blast_radius(hypo_scale, "auth-svc", IncidentSeverity.HIGH)
    assert proposal_scale.risk_tier == RiskTier.LOW
    assert proposal_scale.requires_approval is False

    # Critical risk action: terminating DB backend queries
    hypo_db = RCAHypothesis(
        title="Deadlock",
        root_cause="Locks",
        confidence_score=0.95,
        recommended_action=RemediationActionType.TERMINATE_DB_TRANSACTIONS,
    )
    proposal_db = engine.evaluate_blast_radius(hypo_db, "postgres", IncidentSeverity.CRITICAL)
    assert proposal_db.risk_tier == RiskTier.CRITICAL
    assert proposal_db.requires_approval is True


@pytest.mark.asyncio
async def test_remediation_executor(executor: RemediationExecutor):
    proposal = RemediationProposal(
        action_type=RemediationActionType.SCALE_UP_REPLICAS,
        target_resource="deployment/payment-service",
        parameters={"replicas_delta": 2},
        risk_tier=RiskTier.LOW,
        blast_radius="Stateless scale up",
        rollback_plan="Scale down",
        requires_approval=False,
    )

    # Dry run
    dry_result = await executor.execute_action(proposal, dry_run=True)
    assert dry_result.success is True
    assert "[DRY RUN]" in dry_result.message

    # Live execution
    live_result = await executor.execute_action(proposal, dry_run=False)
    assert live_result.success is True
    assert "scaled up" in live_result.message


@pytest.mark.asyncio
async def test_langgraph_autonomous_flow_auto_approved(investigation_service: InvestigationService):
    """Tests full end-to-end autonomous flow for auto-approved remediation (low risk)."""
    incident_id = "00000000-0000-0000-0000-000000000010"

    result = await investigation_service.start_investigation(
        incident_id=incident_id,
        service="worker-svc",
        symptoms="CPU saturation at 90%",
        severity=IncidentSeverity.MEDIUM,
    )

    state = result["state"]
    assert state["status"] in (
        IncidentStatus.RESOLVED,
        IncidentStatus.MITIGATING,
        IncidentStatus.INVESTIGATING,
    )
    assert state["selected_hypothesis"] is not None
    assert state["execution_result"] is not None
    assert state["verification_report"] is not None
    assert state["postmortem"] is not None
    assert "# Incident Postmortem Report" in state["postmortem"].markdown_content


@pytest.mark.asyncio
async def test_langgraph_hitl_approval_workflow(investigation_service: InvestigationService):
    """Tests Human-In-The-Loop flow: halts at gate, waits for approval, and resumes."""
    incident_id = "00000000-0000-0000-0000-000000000020"

    # 1. Trigger investigation that requires approval (Database deadlock / critical severity)
    trigger_res = await investigation_service.start_investigation(
        incident_id=incident_id,
        service="postgres",
        symptoms="Database deadlock pool timeout error",
        severity=IncidentSeverity.CRITICAL,
    )

    # Must be paused at approval gate
    assert trigger_res["is_awaiting_approval"] is True
    assert "await_approval" in trigger_res["next_steps"]

    # 2. Verify state retrieval shows pending gate
    state_res = await investigation_service.get_state(incident_id)
    assert state_res["is_awaiting_approval"] is True

    # 3. SRE submits human approval
    resume_res = await investigation_service.submit_human_approval(
        incident_id=incident_id,
        approved=True,
        reason="Verified active lock contention on postgres primary. Proceed.",
    )

    assert resume_res["completed"] is True
    resumed_state = resume_res["state"]
    assert resumed_state["approval_status"] == ApprovalStatus.APPROVED
    assert resumed_state["execution_result"] is not None
    assert resumed_state["execution_result"].success is True
    assert resumed_state["verification_report"] is not None
    assert resumed_state["postmortem"] is not None


@pytest.mark.asyncio
async def test_langgraph_hitl_rejection_workflow(investigation_service: InvestigationService):
    """Tests Human-In-The-Loop rejection: SRE rejects, execution is skipped."""
    incident_id = "00000000-0000-0000-0000-000000000030"

    # Trigger critical investigation
    await investigation_service.start_investigation(
        incident_id=incident_id,
        service="postgres",
        symptoms="Deadlock contention",
        severity=IncidentSeverity.CRITICAL,
    )

    # SRE rejects proposed action
    resume_res = await investigation_service.submit_human_approval(
        incident_id=incident_id,
        approved=False,
        reason="Manual DBA intervention underway. Abort automatic query kill.",
    )

    assert resume_res["completed"] is True
    resumed_state = resume_res["state"]
    assert resumed_state["approval_status"] == ApprovalStatus.REJECTED
    # Execution must have been skipped
    assert resumed_state.get("execution_result") is None
    # Postmortem still generated
    assert resumed_state["postmortem"] is not None


@pytest.mark.asyncio
async def test_investigations_api_endpoints(client: httpx.AsyncClient):
    """Tests REST API endpoints for the investigation engine."""
    # 1. Trigger automated investigation
    trigger_payload = {
        "service": "checkout-service",
        "symptoms": "High CPU utilization spike and requests timing out",
        "severity": "high",
    }
    res = await client.post("/api/v1/investigations/trigger", json=trigger_payload)
    assert res.status_code == 200
    data = res.json()
    incident_id = data["incident_id"]
    assert "status" in data
    assert "selected_hypothesis" in data

    # 2. Get state via API
    get_res = await client.get(f"/api/v1/investigations/{incident_id}")
    assert get_res.status_code == 200
    state_data = get_res.json()
    assert state_data["incident_id"] == incident_id

    # Verify database persistence: Incident was automatically created in DB
    db_inc_res = await client.get(f"/api/v1/incidents/{incident_id}")
    assert db_inc_res.status_code == 200
    inc_record = db_inc_res.json()
    assert inc_record["id"] == incident_id
    assert inc_record["service"] == "checkout-service"

    # 3. Trigger approval-requiring incident
    db_payload = {
        "service": "postgres",
        "symptoms": "Deadlock and pool timeout",
        "severity": "critical",
    }
    db_res = await client.post("/api/v1/investigations/trigger", json=db_payload)
    assert db_res.status_code == 200
    db_data = db_res.json()
    db_id = db_data["incident_id"]
    assert db_data["is_awaiting_approval"] is True

    # 4. Approve via API
    approve_res = await client.post(
        f"/api/v1/investigations/{db_id}/approve",
        json={"reason": "Approved by on-call SRE via API"},
    )
    assert approve_res.status_code == 200
    appr_data = approve_res.json()
    assert appr_data["completed"] is True
    assert appr_data["state"]["approval_status"] == "approved"


@pytest.mark.asyncio
async def test_diagnostics_request_feedback_loop(client: httpx.AsyncClient):
    """Tests Section 7/9 requirement: Operator can request more diagnostics to loop back."""
    payload = {
        "service": "payment-api",
        "symptoms": "HTTP 500 errors and pool exhaustion",
        "severity": "critical",
    }
    trigger_res = await client.post("/api/v1/investigations/trigger", json=payload)
    assert trigger_res.status_code == 200
    data = trigger_res.json()
    incident_id = data["incident_id"]
    assert data["is_awaiting_approval"] is True

    # SRE requests more diagnostics
    diag_res = await client.post(
        f"/api/v1/investigations/{incident_id}/diagnostics",
        json={"reason": "Requesting broader 30m window and downstream postgres checks."},
    )
    assert diag_res.status_code == 200
    diag_data = diag_res.json()
    resumed_state = diag_data["state"]
    # Verify retry count incremented and diagnostics expanded
    assert resumed_state.get("retry_count", 0) >= 1
    assert any("Diagnostics expanded" in msg for msg in resumed_state.get("messages", []))


@pytest.mark.asyncio
async def test_required_seven_tools_contract():
    """Validates the 7 required functional tools defined in Section 6."""
    from app.tools import (
        create_incident_report,
        execute_remediation,
        fetch_application_logs,
        get_recent_deployments,
        get_service_dependencies,
        get_system_metrics,
        search_past_incidents,
    )

    # 1. fetch_application_logs — can be empty when service is healthy (no chaos active)
    logs = await fetch_application_logs("payment-api", time_range_minutes=15)
    assert isinstance(logs, list)  # correct: empty when healthy, populated when fault active

    # 2. get_system_metrics
    metrics = await get_system_metrics("payment-api")
    assert metrics.http_error_rate_pct >= 0.0

    # 3. get_recent_deployments
    deployments = await get_recent_deployments("payment-api")
    assert len(deployments) >= 1
    assert deployments[0].version in ("v2.3.1", "v2.3.0")

    # 4. get_service_dependencies
    deps = get_service_dependencies("payment-api")
    assert "postgres" in deps.downstream_services
    assert "order-service" in deps.upstream_services

    # 5. search_past_incidents
    past = await search_past_incidents("connection pool timeout", service="payment-api")
    assert isinstance(past, list)

    # 6. execute_remediation
    rem_res = await execute_remediation(
        action="ROLLBACK_DEPLOYMENT", service="payment-api", approval_id="appr-123"
    )
    assert rem_res.success is True

    # 7. create_incident_report
    mock_state = {
        "incident_id": "test-123",
        "service": "payment-api",
        "symptoms": "Pool exhaustion",
        "severity": IncidentSeverity.CRITICAL,
        "status": IncidentStatus.RESOLVED,
        "iteration_count": 1,
        "selected_hypothesis": None,
        "remediation_proposal": None,
        "execution_result": None,
        "verification_report": None,
        "audit_events": ["Alert triggered", "Remediation executed"],
    }
    report = create_incident_report(mock_state)  # type: ignore[arg-type]
    assert "# Incident Postmortem Report" in report.markdown_content
