import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.enums import (
    AuditAction,
    EvidenceType,
    IncidentSeverity,
    IncidentStatus,
    InvestigationStatus,
    RemediationStatus,
)
from app.models.incident import Incident
from app.models.investigation import Investigation
from app.repository.audit_repo import AuditLogRepository
from app.repository.incident_repo import IncidentRepository
from app.repository.investigation_repo import InvestigationRepository


@pytest.mark.asyncio
async def test_incident_repository_crud(db_session: AsyncSession):
    repo = IncidentRepository(db_session)

    # Create
    incident = Incident(
        title="Payment Gateway Timeout Spike",
        service="payment-gateway",
        severity=IncidentSeverity.CRITICAL,
        description="P99 latency > 8000ms",
        status=IncidentStatus.OPEN,
        extra_metadata={"region": "us-east-1"},
    )
    created = await repo.create(incident)
    assert created.id.startswith("inc-")
    assert created.title == "Payment Gateway Timeout Spike"

    # Get by ID
    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.service == "payment-gateway"

    # List with filters
    results = await repo.list_by_filter(
        service="payment-gateway", severity=IncidentSeverity.CRITICAL
    )
    assert len(results) == 1
    assert results[0].id == created.id

    # Update status
    updated = await repo.update_status(created.id, IncidentStatus.INVESTIGATING)
    assert updated is not None
    assert updated.status == IncidentStatus.INVESTIGATING


@pytest.mark.asyncio
async def test_investigation_repository_workflow(db_session: AsyncSession):
    incident_repo = IncidentRepository(db_session)
    investigation_repo = InvestigationRepository(db_session)

    # Setup parent incident
    incident = await incident_repo.create(
        Incident(
            title="Database Connection Pool Exhaustion",
            service="order-service",
            severity=IncidentSeverity.HIGH,
        )
    )

    # Create investigation
    investigation = Investigation(
        incident_id=incident.id,
        status=InvestigationStatus.RUNNING,
        root_cause_summary="Connection leaks in long-running transactions",
        confidence_score=0.92,
    )
    created_inv = await investigation_repo.create(investigation)
    assert created_inv.id.startswith("inv-")

    # Add evidence
    evidence = await investigation_repo.add_evidence(
        investigation_id=created_inv.id,
        evidence_type=EvidenceType.METRIC,
        source="prometheus",
        summary="Pool saturation at 100% capacity",
        payload={"active_connections": 100, "max_connections": 100},
    )
    assert evidence.id.startswith("evi-")
    assert evidence.evidence_type == EvidenceType.METRIC

    # Add remediation action
    remediation = await investigation_repo.add_remediation_action(
        investigation_id=created_inv.id,
        action_type="restart_service",
        description="Restart order-service pods to clear leaked connections",
        blast_radius="low",
        approval_required=True,
    )
    assert remediation.id.startswith("rem-")
    assert remediation.status == RemediationStatus.PENDING_APPROVAL

    # Update remediation status to approved
    approved = await investigation_repo.update_remediation_status(
        action_id=remediation.id,
        new_status=RemediationStatus.APPROVED,
        approved_by="lead-sre@company.com",
    )
    assert approved is not None
    assert approved.status == RemediationStatus.APPROVED
    assert approved.approved_by == "lead-sre@company.com"

    # Fetch with full relations
    full_inv = await investigation_repo.get_with_details(created_inv.id)
    assert full_inv is not None
    assert len(full_inv.evidences) == 1
    assert len(full_inv.remediations) == 1
    assert full_inv.incident.id == incident.id


@pytest.mark.asyncio
async def test_audit_log_repository(db_session: AsyncSession):
    audit_repo = AuditLogRepository(db_session)

    # Log action
    log_entry = await audit_repo.log(
        entity_type="incident",
        entity_id="inc-test-123",
        action=AuditAction.CREATED,
        actor="oncall-engineer",
        details={"reason": "Manual alert trigger"},
    )
    assert log_entry.id.startswith("aud-")
    assert log_entry.action == AuditAction.CREATED

    # Retrieve history
    history = await audit_repo.list_for_entity("incident", "inc-test-123")
    assert len(history) == 1
    assert history[0].actor == "oncall-engineer"
