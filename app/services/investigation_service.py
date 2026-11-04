import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_investigation_graph
from app.agents.severity import classify_severity
from app.constants.enums import (
    AuditAction,
    EvidenceType,
    IncidentSeverity,
    IncidentStatus,
    InvestigationStatus,
)
from app.exceptions.domain import EntityNotFoundException, InvalidStateTransitionException
from app.models.incident import Incident
from app.models.investigation import Investigation
from app.repository.audit_repo import AuditLogRepository
from app.repository.incident_repo import IncidentRepository
from app.repository.investigation_repo import InvestigationRepository
from app.schemas.agent_state import (
    ApprovalStatus,
    InvestigationState,
)
from app.utils.serialization import as_plain_dict

logger = logging.getLogger("incident_agent.investigation_service")


class InvestigationService:
    """Service orchestrating incident investigations via the LangGraph state machine.

    Supports optional PostgreSQL persistence and audit logging when an AsyncSession is provided,
    while remaining completely decoupled for hermetic unit testing.
    """

    def __init__(
        self,
        graph: CompiledStateGraph[Any, Any, Any, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        self.graph = graph or get_investigation_graph()
        self.session = session
        self.incident_repo = IncidentRepository(session) if session else None
        self.investigation_repo = InvestigationRepository(session) if session else None
        self.audit_repo = AuditLogRepository(session) if session else None

    def _get_config(self, incident_id: str) -> RunnableConfig:
        """Returns LangGraph execution configuration with thread isolation and recursion limits."""
        return RunnableConfig(
            configurable={"thread_id": incident_id},
            recursion_limit=25,
        )

    async def start_investigation(
        self,
        incident_id: str,
        service: str,
        symptoms: str,
        severity: IncidentSeverity | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Initiates an autonomous investigation workflow. `actor` is the signed-in user.

        Without an explicit severity, the level is classified from the symptoms.
        """
        severity = severity or classify_severity(symptoms)
        config = self._get_config(incident_id)

        initial_state: InvestigationState = {
            "incident_id": incident_id,
            "service": service,
            "symptoms": symptoms,
            "severity": severity,
            "status": IncidentStatus.OPEN,
            "iteration_count": 0,
            "retry_count": 0,
            "messages": [f"Triggered investigation on {service}"],
            "affected_services": [service],
            "log_findings": [],
            "metrics": None,
            "deployments": [],
            "retrieved_incidents": [],
            "hypotheses": [],
            "evidence": [],
            "downstream_evidence": [],
            "pending_action": None,
            "approval_status": ApprovalStatus.PENDING,
            "approval_reason": None,
            "executed_actions": [],
            "errors": [],
            "verification_results": None,
            "telemetry": None,
            "log_signatures": [],
            "matched_runbook_ids": [],
            "rca_hypotheses": [],
            "selected_hypothesis": None,
            "remediation_proposal": None,
            "execution_result": None,
            "verification_report": None,
            "postmortem": None,
            "audit_events": [f"Investigation opened by {actor}"],
            "error": None,
        }

        logger.info(f"Invoking LangGraph for incident {incident_id} (thread_id={incident_id})")
        # Invoke workflow until completion or HITL interrupt gate
        result = await self.graph.ainvoke(initial_state, config=config)

        # Inspect if graph paused for human approval
        graph_state = await self.graph.aget_state(config)
        is_awaiting_approval = "await_approval" in graph_state.next

        # Synchronize with PostgreSQL database if session provided
        await self._sync_start_to_db(
            incident_id=incident_id,
            service=service,
            symptoms=symptoms,
            severity=severity,
            state=result,
            is_awaiting_approval=is_awaiting_approval,
        )

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
        request_more_diagnostics: bool = False,
        actor: str = "system",
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

        if request_more_diagnostics:
            new_status = ApprovalStatus.DIAGNOSTICS_REQUESTED
            decision_reason = reason or "Operator requested additional diagnostic evidence."
        elif approved:
            new_status = ApprovalStatus.APPROVED
            decision_reason = reason or "Approved by on-call SRE"
        else:
            new_status = ApprovalStatus.REJECTED
            decision_reason = reason or "Rejected by on-call SRE"

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
                    f"Human decision submitted by {actor}: {new_status.value.upper()} - {decision_reason}"
                ],
            },
            as_node="await_approval",
        )

        # Resume execution from checkpoint
        result = await self.graph.ainvoke(None, config=config)

        resumed_state = await self.graph.aget_state(config)

        # Synchronize decision and final state to PostgreSQL
        await self._sync_approval_to_db(
            incident_id=incident_id,
            approved=approved,
            reason=decision_reason,
            state=result,
            actor=actor,
        )

        return {
            "incident_id": incident_id,
            "state": result,
            "completed": len(resumed_state.next) == 0,
            "next_steps": list(resumed_state.next),
        }

    async def _sync_start_to_db(
        self,
        incident_id: str,
        service: str,
        symptoms: str,
        severity: IncidentSeverity,
        state: dict[str, Any],
        is_awaiting_approval: bool,
    ) -> None:
        """Mirror investigation progress and artifacts to PostgreSQL database."""
        if not self.session or not self.incident_repo or not self.investigation_repo:
            return

        try:
            # 1. Ensure Incident exists
            incident = await self.incident_repo.get_by_id(incident_id)
            if not incident:
                incident = Incident(
                    id=incident_id,
                    title=f"{service} investigation",
                    service=service,
                    severity=severity,
                    status=IncidentStatus.MITIGATING
                    if is_awaiting_approval
                    else IncidentStatus.INVESTIGATING,
                    description=symptoms,
                )
                await self.incident_repo.create(incident)
            else:
                new_status = (
                    IncidentStatus.MITIGATING
                    if is_awaiting_approval
                    else IncidentStatus.INVESTIGATING
                )
                incident.status = new_status

            # 2. Create Investigation
            inv_status = (
                InvestigationStatus.AWAITING_APPROVAL
                if is_awaiting_approval
                else InvestigationStatus.COMPLETED
            )
            top_hypo = state.get("selected_hypothesis")
            investigation = Investigation(
                incident_id=incident_id,
                status=inv_status,
                root_cause_summary=top_hypo.root_cause if top_hypo else None,
                confidence_score=top_hypo.confidence_score if top_hypo else None,
            )
            await self.investigation_repo.create(investigation)

            # 3. Add Evidences
            telemetry = state.get("telemetry")
            if telemetry:
                await self.investigation_repo.add_evidence(
                    investigation_id=investigation.id,
                    evidence_type=EvidenceType.METRIC,
                    source="Prometheus",
                    summary="Golden Signal telemetry snapshot",
                    payload=telemetry.model_dump(mode="json")
                    if hasattr(telemetry, "model_dump")
                    else dict(telemetry),
                )

            logs = state.get("log_signatures", [])
            if logs:
                await self.investigation_repo.add_evidence(
                    investigation_id=investigation.id,
                    evidence_type=EvidenceType.LOG,
                    source="Loki",
                    summary="Top error log signatures",
                    payload={
                        "signatures": [
                            sig.model_dump(mode="json") if hasattr(sig, "model_dump") else dict(sig)
                            for sig in logs
                        ]
                    },
                )

            runbook_ids = state.get("matched_runbook_ids", [])
            if runbook_ids:
                await self.investigation_repo.add_evidence(
                    investigation_id=investigation.id,
                    evidence_type=EvidenceType.RUNBOOK,
                    source="Qdrant",
                    summary="Relevant operational runbooks",
                    payload={"runbook_ids": runbook_ids},
                )

            # 4. Add proposed remediation if present
            proposal = state.get("remediation_proposal")
            if proposal:
                await self.investigation_repo.add_remediation_action(
                    investigation_id=investigation.id,
                    action_type=proposal.action_type.value,
                    description=proposal.blast_radius,
                    blast_radius=proposal.risk_tier.value,
                    approval_required=proposal.requires_approval,
                    execution_payload=proposal.parameters,
                )

            # 5. Audit Log
            if self.audit_repo:
                await self.audit_repo.log(
                    entity_type="investigation",
                    entity_id=investigation.id,
                    action=AuditAction.CREATED,
                    actor="agent",
                    details={"service": service, "status": inv_status.value},
                )

            await self.session.commit()
        except Exception as exc:
            logger.warning(f"Database synchronization failed for incident {incident_id}: {exc}")
            await self.session.rollback()

    async def _sync_approval_to_db(
        self,
        incident_id: str,
        approved: bool,
        reason: str,
        state: dict[str, Any],
        actor: str = "system",
    ) -> None:
        """Update DB models upon human decision, recording who made it."""
        if not self.session or not self.investigation_repo:
            return

        try:
            investigation = await self.investigation_repo.get_latest_for_incident(incident_id)
            if investigation:
                investigation.status = InvestigationStatus.COMPLETED

                if self.audit_repo:
                    await self.audit_repo.log(
                        entity_type="investigation",
                        entity_id=investigation.id,
                        action=AuditAction.APPROVED if approved else AuditAction.REJECTED,
                        actor=actor,
                        details={"reason": reason, "decided_by": actor},
                    )
                if approved:
                    details = await self.investigation_repo.get_with_details(investigation.id)
                    for action in details.remediations if details else []:
                        action.approved_by = actor

            if self.incident_repo:
                new_status = IncidentStatus.RESOLVED if approved else IncidentStatus.INVESTIGATING
                incident = await self.incident_repo.get_by_id(incident_id)
                if incident:
                    incident.status = new_status
                    if approved:
                        incident.resolved_at = datetime.now(UTC)

            await self.session.commit()
        except Exception as exc:
            logger.warning(
                f"Database synchronization on approval failed for incident {incident_id}: {exc}"
            )
            await self.session.rollback()


_default_investigation_service: InvestigationService | None = None


def get_investigation_service() -> InvestigationService:
    global _default_investigation_service
    if _default_investigation_service is None:
        _default_investigation_service = InvestigationService()
    return _default_investigation_service


def summarize_trigger(incident_id: str, service: str, result: dict[str, Any]) -> dict[str, Any]:
    """Builds the JSON response for a started investigation. Shared by the HTTP route and the chat agent."""
    state = result["state"]
    is_awaiting_approval = result["is_awaiting_approval"]

    metrics = as_plain_dict(state.get("metrics") or state.get("telemetry") or {})
    metrics_out: dict[str, Any] = metrics if isinstance(metrics, dict) else {}
    logs_out = [
        as_plain_dict(log) for log in state.get("log_findings") or state.get("log_signatures") or []
    ]
    deps_out = [as_plain_dict(dep) for dep in state.get("deployments") or []]
    past_out = [as_plain_dict(inc) for inc in state.get("retrieved_incidents") or []]

    return {
        "incident_id": incident_id,
        "service": service,
        "status": "AWAITING_HUMAN_APPROVAL" if is_awaiting_approval else "COMPLETED",
        "is_awaiting_approval": is_awaiting_approval,
        "selected_hypothesis": state.get("selected_hypothesis"),
        "remediation_proposal": state.get("remediation_proposal"),
        "execution_result": state.get("execution_result"),
        "verification_report": state.get("verification_report"),
        "postmortem": state.get("postmortem"),
        "audit_events": state.get("audit_events", []),
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
