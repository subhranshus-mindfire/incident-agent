from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.repository.base import BaseRepository
from app.models.incident import Incident
from app.constants.enums import IncidentSeverity, IncidentStatus


class IncidentRepository(BaseRepository[Incident]):
    """Repository handling all incident-specific persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Incident, session)

    async def get_with_relations(self, incident_id: str) -> Optional[Incident]:
        """Fetch an incident by ID along with its associated investigations and details."""
        query = (
            select(Incident)
            .where(Incident.id == incident_id)
            .options(selectinload(Incident.investigations))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_filter(
        self,
        service: Optional[str] = None,
        severity: Optional[IncidentSeverity] = None,
        status: Optional[IncidentStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Incident]:
        """Fetch filtered and paginated list of incidents."""
        query = select(Incident)

        if service:
            query = query.where(Incident.service == service)
        if severity:
            query = query.where(Incident.severity == severity)
        if status:
            query = query.where(Incident.status == status)

        query = query.order_by(Incident.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_status(self, incident_id: str, new_status: IncidentStatus) -> Optional[Incident]:
        """Update the operational status of an incident."""
        incident = await self.get_by_id(incident_id)
        if not incident:
            return None
        incident.status = new_status
        await self.session.flush()
        await self.session.refresh(incident)
        return incident
