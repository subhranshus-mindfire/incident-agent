import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.agents.graph import get_investigation_graph
from app.constants.enums import IncidentSeverity, IncidentStatus
from app.exceptions.domain import EntityNotFoundException, InvalidStateTransitionException
from app.schemas.agent_state import (
    ApprovalStatus,
    InvestigationState,
)

logger = logging.getLogger("incident_agent.investigation_service")


class InvestigationService:
    """Service orchestrating incident investigations via the LangGraph state machine."""

    def __init__(self, graph: CompiledStateGraph[Any, Any, Any, Any] | None = None) -> None:
        self.graph = graph or get_investigation_graph()

    def _get_config(self, incident_id: str) -> RunnableConfig:
        return RunnableConfig(configurable={"thread_id": incident_id})

    async def start_investigation(
        self,
        incident_id: str,
        service: str,
        symptoms: str,
        severity: IncidentSeverity = IncidentSeverity.HIGH,
    ) -> dict[str, Any]:
        """Initiates an autonomous investigation workflow for an incident."""
        config = self._get_config(incident_id)

        initial_state: InvestigationState = {
            "incident_id": incident_id,
            "service": service,
            "symptoms": symptoms,
            "severity": severity,
            "status": IncidentStatus.OPEN,
            "iteration_count": 0,
            "telemetry": None,
            "log_signatures": [],
            "matched_runbook_ids": [],
            "rca_hypotheses": [],
            "selected_hypothesis": None,
            "remediation_proposal": None,
            "approval_status": ApprovalStatus.PENDING,
            "approval_reason": None,
            "execution_result": None,
            "verification_report": None,
            "postmortem": None,
            "audit_events": [f"Triggered investigation for incident {incident_id}"],
            "error": None,
        }

        logger.info(f"Invoking LangGraph for incident {incident_id} (thread_id={incident_id})")
        # Invoke workflow until completion or HITL interrupt gate
        result = await self.graph.ainvoke(initial_state, config=config)

        # Inspect if graph paused for human approval
        graph_state = await self.graph.aget_state(config)
        is_awaiting_approval = "await_approval" in graph_state.next

        return {
            "incident_id": incident_id,
            "state": result,
            "is_awaiting_approval": is_awaiting_approval,
            "next_steps": list(graph_state.next),
        }

    async def get_state(self, incident_id: str) -> dict[str, Any]:
        """Retrieves the live checkpointed state and next execution step for an incident."""
        config = self._get_config(incident_id)
        graph_state = await self.graph.aget_state(config)

        if not graph_state or not graph_state.values:
            raise EntityNotFoundException(entity_name="Investigation", entity_id=incident_id)

        return {
            "incident_id": incident_id,
            "values": graph_state.values,
            "next": list(graph_state.next),
            "is_awaiting_approval": "await_approval" in graph_state.next,
        }

    async def submit_human_approval(
        self,
        incident_id: str,
        approved: bool,
        reason: str = "",
    ) -> dict[str, Any]:
        """Submits human-in-the-loop decision and resumes paused LangGraph execution."""
        config = self._get_config(incident_id)
        graph_state = await self.graph.aget_state(config)

        if not graph_state or not graph_state.values:
            raise EntityNotFoundException(entity_name="Investigation", entity_id=incident_id)

        if "await_approval" not in graph_state.next:
            raise InvalidStateTransitionException(
                current_status="ACTIVE_OR_COMPLETED",
                requested_status="RESUME",
                reason=f"Investigation {incident_id} is not paused at an approval gate.",
            )

        new_status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        decision_reason = reason or (
            "Approved by on-call SRE" if approved else "Rejected by on-call SRE"
        )

        logger.info(
            f"Submitting human decision for incident {incident_id}: {new_status.value} ({decision_reason})"
        )

        # Update checkpointed state with human decision
        await self.graph.aupdate_state(
            config,
            {
                "approval_status": new_status,
                "approval_reason": decision_reason,
                "audit_events": [
                    f"Human decision submitted: {new_status.value.upper()} - {decision_reason}"
                ],
            },
            as_node="await_approval",
        )

        # Resume execution from checkpoint
        result = await self.graph.ainvoke(None, config=config)

        resumed_state = await self.graph.aget_state(config)
        return {
            "incident_id": incident_id,
            "state": result,
            "completed": len(resumed_state.next) == 0,
            "next_steps": list(resumed_state.next),
        }


_default_investigation_service: InvestigationService | None = None


def get_investigation_service() -> InvestigationService:
    global _default_investigation_service
    if _default_investigation_service is None:
        _default_investigation_service = InvestigationService()
    return _default_investigation_service
