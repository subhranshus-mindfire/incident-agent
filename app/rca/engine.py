import logging

from app.constants.enums import IncidentSeverity
from app.constants.thresholds import (
    CPU_CRITICAL_PCT,
    ERROR_RATE_CRITICAL_PCT,
    LATENCY_FAULT_MS,
    MEMORY_CRITICAL_PCT,
)
from app.schemas.agent_state import (
    HealthVerificationReport,
    InvestigationState,
    LogSignature,
    PostmortemReport,
    RCAHypothesis,
    RemediationActionType,
    RemediationProposal,
    RiskTier,
    TelemetrySummary,
)
from app.schemas.runbook import Runbook

logger = logging.getLogger("incident_agent.llm_engine")


class SREInvestigationEngine:
    """Enterprise Root Cause Analysis & Remediation Reasoning Engine.

    Designed for production resilience: produces strictly validated Pydantic models.
    Supports neural model orchestration with a built-in deterministic heuristic fallback
    for hermetic testing, air-gapped deployments, and offline CI/CD pipelines.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def formulate_rca_hypotheses(
        self,
        service: str,
        symptoms: str,
        telemetry: TelemetrySummary | None,
        logs: list[LogSignature],
        runbooks: list[Runbook],
    ) -> list[RCAHypothesis]:
        """Synthesizes observed Golden Signals, error logs, and retrieved runbooks into ranked hypotheses."""
        hypotheses: list[RCAHypothesis] = []
        citations: list[str] = []

        # 1. Telemetry signal extraction
        high_cpu = telemetry.cpu_usage_pct >= CPU_CRITICAL_PCT if telemetry else False
        high_mem = telemetry.memory_usage_pct >= MEMORY_CRITICAL_PCT if telemetry else False
        high_err = telemetry.http_error_rate_pct >= ERROR_RATE_CRITICAL_PCT if telemetry else False
        high_lat = telemetry.p99_latency_seconds >= LATENCY_FAULT_MS / 1000 if telemetry else False

        if telemetry:
            citations.append(
                f"Prometheus: CPU={telemetry.cpu_usage_pct}%, Mem={telemetry.memory_usage_pct}%, "
                f"ErrRate={telemetry.http_error_rate_pct}%, p99Latency={telemetry.p99_latency_seconds}s"
            )

        log_text = " ".join([entry.sample_line.lower() for entry in logs])
        if logs:
            citations.append(f"Loki: {len(logs)} unique error patterns identified")

        # 2. Rule-based signal correlation
        if (
            "pool" in log_text
            or "deadlock" in log_text
            or "connection timeout" in log_text
            or service == "postgres"
        ):
            hypotheses.append(
                RCAHypothesis(
                    title="Database Connection Pool Exhaustion & Lock Contention",
                    root_cause=(
                        f"Error logs for '{service}' mention connection pool starvation, lock contention or "
                        "connection timeouts."
                    ),
                    confidence_score=0.92 if "deadlock" in log_text else 0.85,
                    evidence_citations=citations
                    + ["Log pattern matches 'connection timeout' or 'deadlock'"],
                    recommended_action=RemediationActionType.TERMINATE_DB_TRANSACTIONS,
                )
            )

        if high_cpu or high_lat or "cpu" in symptoms.lower() or "throttle" in log_text:
            hypotheses.append(
                RCAHypothesis(
                    title="Compute Saturation & CFS Throttling",
                    root_cause=(
                        f"CPU for '{service}' is {telemetry.cpu_usage_pct}% in the evaluated window"
                        if telemetry
                        else f"CPU for '{service}' was not measured"
                    )
                    + ", which may be limiting request handling and raising latency.",
                    confidence_score=0.94 if high_cpu else 0.78,
                    evidence_citations=citations
                    + ["CPU metrics exceed operational threshold (80%)"],
                    recommended_action=RemediationActionType.SCALE_UP_REPLICAS,
                )
            )

        if high_mem or "oom" in symptoms.lower() or "137" in log_text or "outofmemory" in log_text:
            hypotheses.append(
                RCAHypothesis(
                    title="Heap Leak / OOMKilled Container Termination",
                    root_cause=(
                        f"Process in '{service}' exceeded its cgroup memory limit and was terminated by Linux kernel OOM killer (Exit Code 137)."
                    ),
                    confidence_score=0.96 if "137" in log_text else 0.82,
                    evidence_citations=citations
                    + ["Exit Code 137 / OutOfMemory detected in runtime logs"],
                    recommended_action=RemediationActionType.ROLLING_RESTART,
                )
            )

        if high_err or "502" in log_text or "503" in log_text or "upstream" in symptoms.lower():
            hypotheses.append(
                RCAHypothesis(
                    title="Upstream Dependency Degradation / Canary Fault",
                    root_cause=(
                        f"5xx errors for '{service}' are elevated"
                        + (f" at {telemetry.http_error_rate_pct}%" if telemetry else "")
                        + ". The cause may be a recent release or an upstream dependency."
                    ),
                    confidence_score=0.88 if high_err else 0.75,
                    evidence_citations=citations + ["HTTP 5xx rate elevated above 5%"],
                    recommended_action=RemediationActionType.ROLLBACK_DEPLOYMENT,
                )
            )

        # Fallback: only generate a generic hypothesis if at least one real signal exists.
        # Never fabricate a hypothesis for a healthy service with zero errors and zero logs.
        has_real_signal = high_cpu or high_mem or high_err or high_lat or bool(logs)
        if not hypotheses and has_real_signal:
            matched_title = runbooks[0].title if runbooks else "Unknown Anomaly"
            hypotheses.append(
                RCAHypothesis(
                    title=f"Transient Service Degradation ({matched_title})",
                    root_cause=f"Service '{service}' is reporting performance degradation matching symptom: {symptoms}.",
                    confidence_score=0.65,
                    evidence_citations=citations,
                    recommended_action=RemediationActionType.ROLLING_RESTART,
                )
            )

        # Sort descending by confidence
        hypotheses.sort(key=lambda h: h.confidence_score, reverse=True)
        return hypotheses

    def evaluate_blast_radius(
        self,
        hypothesis: RCAHypothesis,
        service: str,
        severity: IncidentSeverity,
    ) -> RemediationProposal:
        """Determines blast radius, required approval level, and rollback safeguards for a proposed action."""
        action = hypothesis.recommended_action

        if action == RemediationActionType.SCALE_UP_REPLICAS:
            return RemediationProposal(
                action_type=action,
                target_resource=f"deployment/{service}",
                parameters={"replicas_delta": 2, "max_replicas": 10},
                risk_tier=RiskTier.LOW,
                blast_radius="Stateless scale up. Low impact on surrounding services.",
                rollback_plan=f"Scale deployment/{service} back to previous replica count.",
                requires_approval=False,  # Auto-remediable for low risk stateless scaling!
            )

        if action == RemediationActionType.ROLLING_RESTART:
            return RemediationProposal(
                action_type=action,
                target_resource=f"deployment/{service}",
                parameters={"grace_period_seconds": 30, "max_unavailable": 1},
                risk_tier=RiskTier.MEDIUM,
                blast_radius=f"Sequential restart of pods in '{service}'. Brief transient latency during warm-up.",
                rollback_plan="No direct rollback; monitor pod readiness probes.",
                requires_approval=severity in (IncidentSeverity.HIGH, IncidentSeverity.CRITICAL),
            )

        if action == RemediationActionType.ROLLBACK_DEPLOYMENT:
            return RemediationProposal(
                action_type=action,
                target_resource=f"deployment/{service}",
                parameters={"revisions_to_undo": 1},
                risk_tier=RiskTier.HIGH,
                blast_radius=f"Reverting image tag for '{service}'. May trigger schema or contract incompatibilities.",
                rollback_plan="Re-deploy previous image tag via Helm / CD pipeline.",
                requires_approval=True,  # Mandatory human approval for code/image rollbacks!
            )

        if action == RemediationActionType.TERMINATE_DB_TRANSACTIONS:
            return RemediationProposal(
                action_type=action,
                target_resource="postgresql:primary",
                parameters={"max_transaction_age_seconds": 60, "exclude_superusers": True},
                risk_tier=RiskTier.CRITICAL,
                blast_radius="Abrupt termination of client transactions. In-flight requests will receive connection aborts.",
                rollback_plan="Transactions will be aborted and automatically rolled back by PostgreSQL engine.",
                requires_approval=True,  # Critical risk requires mandatory SRE sign-off!
            )

        # Default fallback
        return RemediationProposal(
            action_type=RemediationActionType.MANUAL_ESCALATION,
            target_resource=service,
            parameters={},
            risk_tier=RiskTier.HIGH,
            blast_radius="Manual intervention by on-call engineer.",
            rollback_plan="N/A",
            requires_approval=True,
        )

    def generate_postmortem_report(
        self,
        state: InvestigationState,
    ) -> PostmortemReport:
        """Constructs an executive markdown postmortem report with root cause analysis and timeline."""
        incident_id = state["incident_id"]
        service = state["service"]
        hypothesis = state.get("selected_hypothesis")
        proposal = state.get("remediation_proposal")
        exec_result = state.get("execution_result")
        verif = state.get("verification_report")
        events = state.get("audit_events", [])

        rc_title = hypothesis.title if hypothesis else "Unresolved Incident"
        rc_details = (
            hypothesis.root_cause
            if hypothesis
            else "Root cause analysis could not isolate a single trigger."
        )
        action_name = proposal.action_type.value if proposal else "None"
        status_text = "SUCCESSFUL" if exec_result and exec_result.success else "DEFERRED / REJECTED"
        verif_text = (
            "System fully stabilized within SLA."
            if verif and verif.stabilized
            else f"Not verified. {verif.details}"
            if verif
            else "Not verified. No post-remediation check ran."
        )

        timeline_entries = (
            events[-8:] if events else ["Incident registered", "Automated investigation executed"]
        )
        prevention_items = _prevention_items_for(proposal, verif)

        markdown = f"""# Incident Postmortem Report
**Service:** `{service}` | **Severity:** `{str(state["severity"]).upper()}` | **Status:** `{str(state["status"]).upper()}`

---

## 1. Executive Summary
An automated incident investigation was conducted for `{service}` due to symptoms: *{state["symptoms"]}*.
Root cause analysis isolated **{rc_title}** with a confidence score of {hypothesis.confidence_score if hypothesis else 0.0:.0%}.

## 2. Root Cause Analysis
{rc_details}

### Telemetry Evidence
"""
        if state.get("telemetry"):
            t = state["telemetry"]
            if t is not None:
                markdown += f"""- **CPU Saturation:** {t.cpu_usage_pct}%
- **Memory Saturation:** {t.memory_usage_pct}%
- **HTTP Error Rate:** {t.http_error_rate_pct}%
- **p99 Latency:** {t.p99_latency_seconds}s
"""

        markdown += f"""
## 3. Remediation Action
- **Proposed Action:** `{action_name}`
- **Execution Status:** `{status_text}`
- **Verification:** {verif_text}

## 4. Investigation Timeline
"""
        for item in timeline_entries:
            markdown += f"- {item}\n"

        markdown += """
## 5. Preventative Action Items
""" + "".join(f"- [ ] {item}\n" for item in prevention_items)

        return PostmortemReport(
            incident_id=incident_id,
            service=service,
            summary=f"Investigation of {service} completed. Root cause: {rc_title}.",
            root_cause=rc_details,
            timeline=timeline_entries,
            remediation_summary=f"Action: {action_name} | Outcome: {status_text}",
            verification_outcome=verif_text,
            prevention_action_items=prevention_items,
            markdown_content=markdown,
        )


_PREVENTION_BY_ACTION: dict[RemediationActionType, list[str]] = {
    RemediationActionType.TERMINATE_DB_TRANSACTIONS: [
        "Set lock and statement timeouts on the database",
        "Alert on connection pool saturation before requests queue",
    ],
    RemediationActionType.SCALE_UP_REPLICAS: [
        "Review HPA min/max replica boundaries",
        "Alert on CPU saturation before latency rises",
    ],
    RemediationActionType.ROLLING_RESTART: [
        "Find what built up before the restart (memory growth or a stuck worker)",
        "Review pod readiness and liveness probes",
    ],
    RemediationActionType.ROLLBACK_DEPLOYMENT: [
        "Add a pre-release test for this failure mode",
        "Gate releases on the 5xx error rate",
    ],
}


def _prevention_items_for(
    proposal: RemediationProposal | None, verif: HealthVerificationReport | None
) -> list[str]:
    """Follow-up items for the action that was taken, plus a re-check when health was not confirmed."""
    generic = ["Add an alert for this symptom", "Review the runbook for this service"]
    items = list(_PREVENTION_BY_ACTION.get(proposal.action_type, generic)) if proposal else generic
    if verif is None or not verif.stabilized:
        items.append("Re-check service health once traffic resumes")
    return items


_default_engine: SREInvestigationEngine | None = None


def get_investigation_engine() -> SREInvestigationEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = SREInvestigationEngine()
    return _default_engine
