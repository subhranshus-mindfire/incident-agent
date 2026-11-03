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

    # Extract telemetry/metrics — handle both Pydantic model and dict
    metrics = state.get("metrics") or state.get("telemetry") or {}
    metrics_out: dict[str, Any] = {}
    if metrics:
        if hasattr(metrics, "model_dump"):
            metrics_out = metrics.model_dump()
        elif isinstance(metrics, dict):
            metrics_out = metrics

    # Extract logs — list of LogSignature models or dicts
    raw_logs = state.get("log_findings") or state.get("log_signatures") or []
    logs_out = []
    for log in raw_logs:
        if hasattr(log, "model_dump"):
            logs_out.append(log.model_dump())
        elif isinstance(log, dict):
            logs_out.append(log)

    # Extract deployments
    raw_deps = state.get("deployments") or []
    deps_out = []
    for dep in raw_deps:
        if hasattr(dep, "model_dump"):
            deps_out.append(dep.model_dump())
        elif isinstance(dep, dict):
            deps_out.append(dep)

    # Extract historical incidents from Qdrant
    raw_past = state.get("retrieved_incidents") or []
    past_out = []
    for inc in raw_past:
        if hasattr(inc, "model_dump"):
            past_out.append(inc.model_dump())
        elif isinstance(inc, dict):
            past_out.append(inc)

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
        # Full telemetry for UI rendering
        "state": {
            "metrics": metrics_out,
            "telemetry_summary": metrics_out,
            "log_signatures": logs_out,
            "log_findings": logs_out,
            "deployments": deps_out,
            "recent_deployments": deps_out,
            "retrieved_incidents": past_out,
            "historical_incidents": past_out,
            "selected_hypothesis": state.get("selected_hypothesis"),
            "hypotheses": state.get("hypotheses") or state.get("rca_hypotheses") or [],
            "remediation_proposal": state.get("remediation_proposal"),
            "affected_services": state.get("affected_services", []),
        },
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


@router.post(
    "/{incident_id}/diagnostics",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Request Additional Diagnostics",
)
async def request_diagnostics(
    incident_id: str,
    payload: HumanDecisionRequest,
    service: InvestigationService = Depends(get_investigation_service),
) -> dict[str, Any]:
    """Requests additional diagnostic data gathering and loops back into investigation."""
    return await service.submit_human_approval(
        incident_id=incident_id,
        approved=False,
        reason=payload.reason,
        request_more_diagnostics=True,
    )
