import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.enums import AuditAction, IncidentSeverity, IncidentStatus
from app.models.incident import Incident
from app.repository.audit_repo import AuditLogRepository
from app.repository.incident_repo import IncidentRepository
from app.schemas.incident import IncidentCreate

logger = logging.getLogger("incident_agent.incident_service")


class IncidentService:
    """Business service governing incident lifecycle management."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.incident_repo = IncidentRepository(session)
        self.audit_repo = AuditLogRepository(session)

    async def create_incident(self, payload: IncidentCreate, actor: str = "system") -> Incident:
        """Create and persist a new incident with an audit log."""
        incident = Incident(
            title=payload.title,
            service=payload.service,
            severity=IncidentSeverity(payload.severity),
            description=payload.description,
            status=IncidentStatus.OPEN,
            extra_metadata=payload.extra_metadata or {},
        )
        created_incident = await self.incident_repo.create(incident)

        # Audit entry
        await self.audit_repo.log(
            entity_type="incident",
            entity_id=created_incident.id,
            action=AuditAction.CREATED,
            actor=actor,
            details={
                "title": created_incident.title,
                "service": created_incident.service,
                "severity": created_incident.severity.value,
            },
        )
        logger.info("Incident created successfully with ID: %s", created_incident.id)
        return created_incident

    async def get_incident(self, incident_id: str) -> Incident | None:
        """Fetch incident by ID."""
        return await self.incident_repo.get_with_relations(incident_id)

    async def list_incidents(
        self,
        service: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Incident]:
        """Retrieve paginated incidents with optional filters."""
        sev_enum = IncidentSeverity(severity) if severity else None
        stat_enum = IncidentStatus(status) if status else None
        return await self.incident_repo.list_by_filter(
            service=service,
            severity=sev_enum,
            status=stat_enum,
            skip=skip,
            limit=limit,
        )

    async def update_status(
        self,
        incident_id: str,
        new_status: IncidentStatus,
        actor: str = "system",
        reason: str | None = None,
    ) -> Incident | None:
        """Update incident status and log the change."""
        updated = await self.incident_repo.update_status(incident_id, new_status)
        if updated:
            await self.audit_repo.log(
                entity_type="incident",
                entity_id=incident_id,
                action=AuditAction.STATUS_CHANGED,
                actor=actor,
                details={"new_status": new_status.value, "reason": reason},
            )
            logger.info("Incident %s transitioned to %s", incident_id, new_status.value)
        return updated
