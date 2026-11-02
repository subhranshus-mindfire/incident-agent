import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.incident_service import IncidentService
from app.schemas.incident import IncidentCreate
from app.constants.enums import IncidentSeverity, IncidentStatus, AuditAction
from app.repository.audit_repo import AuditLogRepository


@pytest.mark.asyncio
async def test_incident_service_create_and_audit(db_session: AsyncSession):
    service = IncidentService(db_session)
    audit_repo = AuditLogRepository(db_session)

    payload = IncidentCreate(
        title="High Error Rate in Auth Service",
        service="auth-service",
        severity=IncidentSeverity.CRITICAL,
        description="500 Internal Server Errors surged to 18%",
        extra_metadata={"datacenter": "us-west-2"},
    )

    incident = await service.create_incident(payload, actor="sre-bot")
    assert incident.id.startswith("inc-")
    assert incident.status == IncidentStatus.OPEN

    # Verify audit log was created
    audit_trail = await audit_repo.list_for_entity("incident", incident.id)
    assert len(audit_trail) == 1
    assert audit_trail[0].action == AuditAction.CREATED
    assert audit_trail[0].actor == "sre-bot"


@pytest.mark.asyncio
async def test_incident_service_update_status(db_session: AsyncSession):
    service = IncidentService(db_session)
    audit_repo = AuditLogRepository(db_session)

    payload = IncidentCreate(
        title="Kubernetes Pod CrashLoopBackOff",
        service="inventory-service",
        severity=IncidentSeverity.HIGH,
    )
    incident = await service.create_incident(payload)

    # Transition status
    updated = await service.update_status(
        incident_id=incident.id,
        new_status=IncidentStatus.INVESTIGATING,
        actor="lead-investigator",
        reason="Agent investigation graph triggered",
    )
    assert updated is not None
    assert updated.status == IncidentStatus.INVESTIGATING

    # Verify audit history
    audit_trail = await audit_repo.list_for_entity("incident", incident.id)
    assert len(audit_trail) == 2
    actions = [a.action for a in audit_trail]
    assert AuditAction.CREATED in actions
    assert AuditAction.STATUS_CHANGED in actions

    status_change_log = next(a for a in audit_trail if a.action == AuditAction.STATUS_CHANGED)
    assert status_change_log.details["new_status"] == IncidentStatus.INVESTIGATING.value
