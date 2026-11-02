from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db_session
from app.services.incident_service import IncidentService
from app.schemas.incident import IncidentCreate, IncidentResponse, IncidentUpdateStatus
from app.constants.enums import IncidentStatus, IncidentSeverity
from app.exceptions.domain import IncidentNotFoundException

router = APIRouter(prefix="/incidents", tags=["Incidents"])


def get_incident_service(session: AsyncSession = Depends(get_db_session)) -> IncidentService:
    """Dependency provider for IncidentService."""
    return IncidentService(session)


@router.get("", response_model=List[IncidentResponse], status_code=status.HTTP_200_OK)
async def list_incidents(
    service: Optional[str] = Query(None, description="Filter by service name"),
    severity: Optional[IncidentSeverity] = Query(None, description="Filter by severity"),
    incident_status: Optional[IncidentStatus] = Query(None, alias="status", description="Filter by status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    incident_service: IncidentService = Depends(get_incident_service),
) -> List[IncidentResponse]:
    """Retrieve filtered and paginated incidents."""
    incidents = await incident_service.list_incidents(
        service=service,
        severity=severity.value if severity else None,
        status=incident_status.value if incident_status else None,
        skip=skip,
        limit=limit,
    )
    return [IncidentResponse.model_validate(inc) for inc in incidents]


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: IncidentCreate,
    incident_service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Register or ingest a new incident into the system."""
    incident = await incident_service.create_incident(payload)
    return IncidentResponse.model_validate(incident)


@router.get("/{incident_id}", response_model=IncidentResponse, status_code=status.HTTP_200_OK)
async def get_incident(
    incident_id: str,
    incident_service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Retrieve details of a specific incident."""
    incident = await incident_service.get_incident(incident_id)
    if not incident:
        raise IncidentNotFoundException(incident_id)
    return IncidentResponse.model_validate(incident)


@router.patch("/{incident_id}/status", response_model=IncidentResponse, status_code=status.HTTP_200_OK)
async def update_incident_status(
    incident_id: str,
    payload: IncidentUpdateStatus,
    incident_service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Update incident operational status."""
    updated = await incident_service.update_status(
        incident_id=incident_id,
        new_status=payload.status,
        reason=payload.reason,
    )
    if not updated:
        raise IncidentNotFoundException(incident_id)
    return IncidentResponse.model_validate(updated)
