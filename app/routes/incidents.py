import uuid
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, HTTPException, status
from app.schemas.incident import IncidentCreate, IncidentResponse

router = APIRouter(prefix="/incidents", tags=["Incidents"])

# In-memory store placeholder until database connection is wired
_incidents_db: List[dict] = [
    {
        "id": "inc-sim-001",
        "title": "High Latency & 504 Gateway Timeouts",
        "service": "checkout-service",
        "severity": "critical",
        "description": "P99 latency spiked past 5000ms after v1.2.0 deployment",
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"source": "prometheus_alert"}
    }
]


@router.get("", response_model=List[IncidentResponse])
async def list_incidents() -> List[IncidentResponse]:
    """Retrieve all recorded incidents."""
    return [IncidentResponse(**inc) for inc in _incidents_db]


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(payload: IncidentCreate) -> IncidentResponse:
    """Register or simulate a new production incident."""
    incident_dict = {
        "id": f"inc-{uuid.uuid4().hex[:8]}",
        "title": payload.title,
        "service": payload.service,
        "severity": payload.severity,
        "description": payload.description,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {}
    }
    _incidents_db.append(incident_dict)
    return IncidentResponse(**incident_dict)


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str) -> IncidentResponse:
    """Retrieve details for a specific incident."""
    for inc in _incidents_db:
        if inc["id"] == incident_id:
            return IncidentResponse(**inc)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Incident with ID '{incident_id}' not found."
    )
