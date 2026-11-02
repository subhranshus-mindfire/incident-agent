import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db_session
from app.constants.enums import IncidentSeverity
from app.services.investigation_service import InvestigationService

logger = logging.getLogger("incident_agent.routes.investigations")

router = APIRouter(prefix="/investigations", tags=["Investigations & LangGraph Agent"])


def get_investigation_service(
    session: AsyncSession = Depends(get_db_session),
) -> InvestigationService:
    """Dependency provider injecting database session into InvestigationService."""
    return InvestigationService(session=session)


class TriggerInvestigationRequest(BaseModel):
    incident_id: str | None = Field(
        default=None, description="Optional incident UUID. Generated if omitted."
    )
    service: str = Field(..., min_length=1, description="Target microservice identifier")
    symptoms: str = Field(
        ..., min_length=5, description="Observed symptom or alert notification text"
    )
    severity: IncidentSeverity = Field(
        default=IncidentSeverity.HIGH, description="Incident severity level"
    )


class HumanDecisionRequest(BaseModel):
    reason: str = Field(default="", description="Operator notes or reasoning for decision")


@router.post(
    "/trigger",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Trigger Automated Incident Investigation",
)
async def trigger_investigation(
    payload: TriggerInvestigationRequest,
    service: InvestigationService = Depends(get_investigation_service),
) -> dict[str, Any]:
    """Initiates an autonomous investigation workflow via LangGraph."""
    incident_id = payload.incident_id or str(uuid4())

    result = await service.start_investigation(
        incident_id=incident_id,
        service=payload.service,
        symptoms=payload.symptoms,
        severity=payload.severity,
    )

    state = result["state"]
    is_awaiting_approval = result["is_awaiting_approval"]

    return {
        "incident_id": incident_id,
        "service": payload.service,
        "status": "AWAITING_HUMAN_APPROVAL" if is_awaiting_approval else "COMPLETED",
        "is_awaiting_approval": is_awaiting_approval,
        "selected_hypothesis": state.get("selected_hypothesis"),
        "remediation_proposal": state.get("remediation_proposal"),
        "execution_result": state.get("execution_result"),
        "verification_report": state.get("verification_report"),
        "postmortem": state.get("postmortem"),
        "audit_events": state.get("audit_events", []),
    }


@router.get(
    "/{incident_id}",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get Investigation Live State",
)
async def get_investigation_state(
    incident_id: str,
    service: InvestigationService = Depends(get_investigation_service),
) -> dict[str, Any]:
    """Retrieves current checkpoint state and execution progress for an incident."""
    return await service.get_state(incident_id)


@router.post(
    "/{incident_id}/approve",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Submit Human Approval for Remediation",
)
async def approve_remediation(
    incident_id: str,
    payload: HumanDecisionRequest,
    service: InvestigationService = Depends(get_investigation_service),
) -> dict[str, Any]:
    """Approves proposed remediation and resumes the paused LangGraph workflow."""
    return await service.submit_human_approval(
        incident_id=incident_id,
        approved=True,
        reason=payload.reason,
    )


@router.post(
    "/{incident_id}/reject",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Reject Proposed Remediation",
)
async def reject_remediation(
    incident_id: str,
    payload: HumanDecisionRequest,
    service: InvestigationService = Depends(get_investigation_service),
) -> dict[str, Any]:
    """Rejects proposed remediation and finishes the workflow with an aborted status."""
    return await service.submit_human_approval(
        incident_id=incident_id,
        approved=False,
        reason=payload.reason,
    )
