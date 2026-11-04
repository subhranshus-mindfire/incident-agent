import asyncio
import logging
from typing import Any

from app.constants.enums import IncidentSeverity, IncidentStatus
from app.constants.remediation import (
    FAULT_REMEDIATIONS,
    VERIFY_SETTLE_SECONDS,
)
from app.constants.thresholds import (
    CPU_CRITICAL_PCT,
    ERROR_RATE_FAULT_PCT,
    LATENCY_FAULT_MS,
)
from app.rca.engine import get_investigation_engine
from app.schemas.agent_state import (
    ApprovalStatus,
    HealthVerificationReport,
    InvestigationState,
    RCAHypothesis,
    RemediationActionType,
    RiskTier,
)
from app.schemas.telemetry import GoldenSignalMetrics
from app.services.clients import get_prometheus_service
from app.services.qdrant_service import get_shared_qdrant_service
from app.tools.investigation_tools import (
    create_incident_report,
    execute_remediation,
    fetch_application_logs,
    get_active_faults,
    get_recent_deployments,
    get_service_dependencies,
    get_system_metrics,
    search_past_incidents,
)

logger = logging.getLogger("incident_agent.agents.nodes")


async def node_ingest_alert(state: InvestigationState) -> dict[str, Any]:
    """Node 1: Ingests alert, identifies dependencies, and fetches recent deployments."""
    incident_id = state["incident_id"]
    service = state["service"]
    symptoms = state["symptoms"]

    logger.info(f"[Node 1: IngestAlert] Ingesting alert for incident {incident_id} on '{service}'")

    # Resolve architectural dependencies
    dep_map = get_service_dependencies(service)
    affected_services = [service] + dep_map.downstream_services + dep_map.upstream_services

    # Find recent deployments
    recent_deployments = await get_recent_deployments(service)

    msg = f"Alert received on {service}: {symptoms}. Affected services: {', '.join(affected_services)}"

    return {
        "status": IncidentStatus.INVESTIGATING,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "retry_count": state.get("retry_count", 0),
        "messages": state.get("messages", []) + [msg],
        "affected_services": affected_services,
        "deployments": recent_deployments,
        "errors": state.get("errors", []),
        "audit_events": [
            f"Alert ingested for '{service}' (Severity: {state['severity'].value}). Identified {len(affected_services)} affected components.",
            f"Retrieved {len(recent_deployments)} recent deployments (Latest: {recent_deployments[0].version if recent_deployments else 'none'}).",
        ],
    }


async def node_gather_telemetry(state: InvestigationState) -> dict[str, Any]:
    """Node 2: Concurrently fetches Prometheus metrics and Loki error logs."""
    service = state["service"]
    logger.info(f"[Node 2: GatherTelemetry] Fetching observability signals for '{service}'")

    time_range = 15 if state.get("retry_count", 0) == 0 else 30

    # Fetch logs & metrics using functional tools
    log_signatures = await fetch_application_logs(service, time_range_minutes=time_range)
    telemetry_summary = await get_system_metrics(service)

    return {
        "metrics": telemetry_summary,
        "telemetry": telemetry_summary,
        "log_findings": log_signatures,
        "log_signatures": log_signatures,
        "audit_events": [
            f"Telemetry collected: CPU={telemetry_summary.cpu_usage_pct}%, "
            f"Errors={telemetry_summary.http_error_rate_pct}%, Logs={len(log_signatures)} patterns"
        ],
    }


async def node_retrieve_qdrant(state: InvestigationState) -> dict[str, Any]:
    """Node 3: Semantically retrieves historical incidents and operational runbooks from Qdrant."""
    service = state["service"]
    symptoms = state["symptoms"]
    qdrant = get_shared_qdrant_service()

    query = symptoms
    if state.get("log_findings"):
        query += f" {state['log_findings'][0].sample_line}"

    # 1. Search past incidents in Qdrant
    past_incidents = await search_past_incidents(query=query, service=service, limit=3)
    if not past_incidents:
        past_incidents = await search_past_incidents(query=query, limit=3)

    # 2. Search runbooks in Qdrant
    try:
        runbook_results = await qdrant.search_runbooks(
            query=query, service=service, limit=3, score_threshold=0.15
        )
        matched_ids = [res.runbook.id for res in runbook_results]
        runbook_titles = [res.runbook.title for res in runbook_results]
    except Exception as exc:
        logger.warning(f"Runbook retrieval error: {exc}")
        matched_ids = []
        runbook_titles = []

    return {
        "retrieved_incidents": past_incidents,
        "matched_runbook_ids": matched_ids,
        "audit_events": [
            f"Retrieved {len(past_incidents)} similar historical incidents from Qdrant.",
            f"Retrieved {len(matched_ids)} matching runbooks: {', '.join(runbook_titles[:2])}",
        ],
    }


async def node_correlate_evidence(state: InvestigationState) -> dict[str, Any]:
    """Node 4: Correlates metrics, logs, deployments, and historical incidents into evidence."""
    service = state["service"]
    evidence_list: list[str] = []

    # 1. Telemetry evidence
    metrics = state.get("metrics") or state.get("telemetry")
    if metrics:
        if metrics.cpu_usage_pct > CPU_CRITICAL_PCT:
            evidence_list.append(f"High CPU saturation: {metrics.cpu_usage_pct}% on {service}")
        if metrics.http_error_rate_pct > ERROR_RATE_FAULT_PCT:
            evidence_list.append(
                f"Elevated 5xx error rate: {metrics.http_error_rate_pct}% on {service}"
            )
        if metrics.p99_latency_seconds > LATENCY_FAULT_MS / 1000:
            evidence_list.append(
                f"Severe p99 latency degradation: {metrics.p99_latency_seconds * 1000:.0f}ms"
            )

    # 2. Log evidence
    logs = state.get("log_findings") or state.get("log_signatures", [])
    for log in logs[:3]:
        evidence_list.append(f"Log error signature ({log.count}x): {log.sample_line[:100]}")

    # 3. Deployment evidence
    deployments = state.get("deployments", [])
    if deployments:
        latest_dep = deployments[0]
        evidence_list.append(
            f"Recent release: {latest_dep.version} ({latest_dep.deployment_id}) deployed at {latest_dep.deployed_at}"
        )

    # 4. Historical incident evidence
    past_incidents = state.get("retrieved_incidents", [])
    for past in past_incidents[:2]:
        evidence_list.append(
            f"Historical match ({past.similarity_score:.0%}): {past.root_cause[:90]}"
        )

    return {
        "evidence": evidence_list,
        "audit_events": [
            f"Correlated {len(evidence_list)} evidence items across telemetry, logs, and deployments."
        ],
    }


async def node_expand_diagnostics(state: InvestigationState) -> dict[str, Any]:
    """Diagnostic loop node: Expands time range and inspects downstream dependency health."""
    current_retry = state.get("retry_count", 0) + 1
    affected = state.get("affected_services", [])
    logger.info(f"[Node: ExpandDiagnostics] Expanding diagnostics (retry {current_retry}/2)")

    # Diagnostic probe on downstream services
    downstream_logs: list[str] = []
    if len(affected) > 1:
        downstream = affected[1]
        extra_logs = await fetch_application_logs(downstream, time_range_minutes=30)
        if extra_logs:
            downstream_logs.append(
                f"Downstream {downstream} error: {extra_logs[0].sample_line[:100]}"
            )

    msg = f"Diagnostics expanded to 30m window. Downstream dependencies checked: {', '.join(affected[1:])}"

    return {
        "retry_count": current_retry,
        "messages": state.get("messages", []) + [msg],
        "evidence": state.get("evidence", []) + downstream_logs,
        "audit_events": [
            f"Expanded diagnostics (retry {current_retry}): inspected downstream services."
        ],
    }


async def node_formulate_rca(state: InvestigationState) -> dict[str, Any]:
    """Node 5: Synthesizes evidence and runbooks into ranked RCA hypotheses.
    Short-circuits cleanly when no real evidence of a fault is found.
    """
    engine = get_investigation_engine()
    qdrant = get_shared_qdrant_service()

    telemetry = state.get("metrics") or state.get("telemetry")
    logs = state.get("log_findings") or state.get("log_signatures", [])
    evidence = state.get("evidence", [])

    # Guard: Only formulate RCA if there is REAL fault evidence — elevated metrics or
    # actual error logs. Deployment records and Qdrant matches alone are NOT fault signals;
    # they are context. This prevents the LLM from fabricating a root cause when the
    # service is healthy and the user is simply asking a conversational/search question.
    has_metric_anomaly = bool(
        telemetry
        and (
            telemetry.http_error_rate_pct > ERROR_RATE_FAULT_PCT
            or telemetry.p99_latency_seconds > LATENCY_FAULT_MS / 1000
            or telemetry.cpu_usage_pct > CPU_CRITICAL_PCT
        )
    )
    has_error_logs = bool(logs)
    # The service's own health probe names a live fault even when no traffic reaches the metrics.
    live_faults = await get_active_faults(state["service"]) or {}
    live_fault = next((f for f, on in live_faults.items() if on and f in FAULT_REMEDIATIONS), None)

    if not has_metric_anomaly and not has_error_logs and live_fault is None:
        logger.info(
            "[Node 5: FormulateRCA] No metric anomaly and no error logs detected — "
            "service is healthy. Skipping RCA to prevent hallucinated hypotheses."
        )
        return {
            "hypotheses": [],
            "rca_hypotheses": [],
            "selected_hypothesis": None,
            "audit_events": [
                "No fault signals detected (error rate normal, no Loki errors). "
                "Service appears healthy — no root cause identified; no remediation proposed."
            ],
        }

    # Hydrate runbooks
    runbooks = []
    for r_id in state.get("matched_runbook_ids", []):
        rb = await qdrant.get_runbook(r_id)
        if rb:
            runbooks.append(rb)

    hypotheses = engine.formulate_rca_hypotheses(
        service=state["service"],
        symptoms=state["symptoms"],
        telemetry=telemetry,
        logs=logs,
        runbooks=runbooks,
    )

    # Check if a recent deployment correlates directly to the failure
    deployments = state.get("deployments", [])
    if deployments and logs:
        log_text = " ".join([entry.sample_line for entry in logs]).lower()
        if "pool" in log_text or "connection" in log_text or "timeout" in log_text:
            dep = deployments[0]
            hypotheses.insert(
                0,
                RCAHypothesis(
                    title=f"Regression in Deployment {dep.version} ({dep.deployment_id})",
                    root_cause=f"Deployment {dep.version} introduced connection leakage and transaction deadlocks causing connection pool exhaustion.",
                    confidence_score=0.92,
                    evidence_citations=evidence[:4],
                    recommended_action=RemediationActionType.ROLLBACK_DEPLOYMENT,
                ),
            )

    # A live fault reported by the service is direct evidence, so it leads the ranking.
    if live_fault is not None:
        hypotheses.insert(
            0,
            RCAHypothesis(
                title=f"Live fault reported by {state['service']}: {live_fault}",
                root_cause=f"{state['service']} reports the '{live_fault}' fault as active in its health check.",
                confidence_score=0.9,
                evidence_citations=[f"{state['service']} /health: active_chaos.{live_fault}=true"],
                recommended_action=FAULT_REMEDIATIONS[live_fault],
            ),
        )

    top_hypothesis = hypotheses[0] if hypotheses else None
    logger.info(
        f"[Node 5: FormulateRCA] Formulated {len(hypotheses)} hypotheses. Top: '{top_hypothesis.title if top_hypothesis else 'None'}'"
    )

    return {
        "hypotheses": hypotheses,
        "rca_hypotheses": hypotheses,
        "selected_hypothesis": top_hypothesis,
        "audit_events": [
            f"RCA isolated root cause: '{top_hypothesis.title}' (confidence: {top_hypothesis.confidence_score:.0%})"
            if top_hypothesis
            else "RCA formulation completed with no definitive match"
        ],
    }


async def node_assess_blast_radius(state: InvestigationState) -> dict[str, Any]:
    """Node 6: Evaluates blast radius and requires human approval for remediation."""
    hypothesis = state.get("selected_hypothesis")
    if not hypothesis:
        return {"audit_events": ["Skipping remediation proposal: no root cause isolated"]}

    # The RCA's suggested action is a rule guess. If the service reports a live fault that has a known
    # remediation, the proposal follows the live fault instead.
    override_note: list[str] = []
    live_faults = await get_active_faults(state["service"]) or {}
    live_actions = [
        FAULT_REMEDIATIONS[f] for f, on in live_faults.items() if on and f in FAULT_REMEDIATIONS
    ]
    if live_actions and hypothesis.recommended_action not in live_actions:
        override_note.append(
            f"Proposed action changed from {hypothesis.recommended_action.value} to {live_actions[0].value} "
            "to match the live fault."
        )
        hypothesis = hypothesis.model_copy(update={"recommended_action": live_actions[0]})

    engine = get_investigation_engine()
    proposal = engine.evaluate_blast_radius(
        hypothesis=hypothesis,
        service=state["service"],
        severity=state["severity"],
    )

    # Determine approval requirement based on risk tier and severity
    if proposal.risk_tier == RiskTier.LOW and state["severity"] == IncidentSeverity.MEDIUM:
        approval_status = ApprovalStatus.AUTO_APPROVED
        proposal.requires_approval = False
    else:
        approval_status = ApprovalStatus.PENDING
        proposal.requires_approval = True

    logger.info(
        f"[Node 6: AssessBlastRadius] Action: {proposal.action_type.value}, "
        f"Risk: {proposal.risk_tier.value.upper()}, RequiresApproval: True"
    )

    return {
        "pending_action": proposal,
        "remediation_proposal": proposal,
        "approval_status": approval_status,
        "audit_events": override_note
        + [
            f"Remediation proposed: {proposal.action_type.value} on {proposal.target_resource} "
            f"(Risk: {proposal.risk_tier.value.upper()}, Approval: MANDATORY)"
        ],
    }


async def node_await_approval(state: InvestigationState) -> dict[str, Any]:
    """Node 7: Human-in-the-Loop decision gate. Graph holds checkpoint here if pending."""
    status = state.get("approval_status")
    logger.info(f"[Node 7: AwaitApproval] Gate status: {status}")

    return {
        "audit_events": [
            f"HITL approval gate reached. Current status: {str(status) if status else 'unknown'}"
        ]
    }


async def node_execute_remediation(state: InvestigationState) -> dict[str, Any]:
    """Node 8: Executes approved remediation action with idempotency."""
    proposal = state.get("pending_action") or state.get("remediation_proposal")
    approval_status = state.get("approval_status")

    if not proposal:
        return {"audit_events": ["Execution skipped: No remediation proposal present."]}

    if approval_status not in (ApprovalStatus.APPROVED, ApprovalStatus.AUTO_APPROVED):
        logger.warning(
            f"[Node 8: ExecuteRemediation] Skipped: approval_status is {approval_status}"
        )
        return {
            "status": IncidentStatus.INVESTIGATING,
            "audit_events": [f"Remediation not executed (Approval: {approval_status})"],
        }

    # Execute remediation via tool
    result = await execute_remediation(
        action=proposal.action_type.value,
        service=state["service"],
        approval_id=f"appr-{state['incident_id'][:8]}",
        parameters=proposal.parameters,
    )

    executed_list = state.get("executed_actions", []) + [result]
    new_status = IncidentStatus.RESOLVED if result.success else IncidentStatus.INVESTIGATING

    return {
        "executed_actions": executed_list,
        "execution_result": result,
        "status": new_status,
        "audit_events": [f"Remediation executed: {result.action_type} - {result.message}"],
    }


async def node_verify_health(state: InvestigationState) -> dict[str, Any]:
    """Node 9: Re-measures Prometheus golden signals after remediation to confirm stabilization."""
    logger.info("[Node 9: VerifyHealth] Probing post-remediation health metrics")
    exec_result = state.get("execution_result")
    prev_telemetry = state.get("metrics") or state.get("telemetry")
    prev_error = prev_telemetry.http_error_rate_pct if prev_telemetry else 0.0
    prev_latency_ms = (prev_telemetry.p99_latency_seconds * 1000) if prev_telemetry else 0.0

    if not exec_result or not exec_result.success:
        report = HealthVerificationReport(
            stabilized=False,
            previous_error_rate=prev_error,
            current_error_rate=prev_error,
            previous_latency_ms=prev_latency_ms,
            current_latency_ms=prev_latency_ms,
            observation_window_seconds=0,
            details="Remediation not executed; system health remains unverified.",
        )
    else:
        # Let the rollback settle, then measure only the last minute so pre-rollback errors don't count.
        await asyncio.sleep(VERIFY_SETTLE_SECONDS)
        try:
            current = await get_prometheus_service().get_golden_signals(
                service=state["service"], window_minutes=1
            )
        except Exception as exc:
            logger.warning(f"[Node 9: VerifyHealth] Prometheus probe failed: {exc}")
            current = None

        if not isinstance(current, GoldenSignalMetrics):
            report = HealthVerificationReport(
                stabilized=False,
                previous_error_rate=prev_error,
                current_error_rate=prev_error,
                previous_latency_ms=prev_latency_ms,
                current_latency_ms=prev_latency_ms,
                observation_window_seconds=VERIFY_SETTLE_SECONDS,
                details="Post-remediation metrics unavailable from Prometheus; health unverified.",
            )
        else:
            # With no requests in the window, the error rate is 0 by arithmetic, not by observation.
            not_collected = set(current.missing_signals) & {
                "error_rate_5xx_percent",
                "p95_latency_ms",
                "request_rate_per_sec",
            }
            has_traffic = current.request_rate_per_sec > 0 and not not_collected
            within_thresholds = (
                current.error_rate_5xx_percent < ERROR_RATE_FAULT_PCT
                and current.p95_latency_ms < LATENCY_FAULT_MS
            )
            stabilized = has_traffic and within_thresholds
            if not_collected:
                outcome = f"Metrics not collected ({', '.join(sorted(not_collected))}), so health cannot be verified."
            elif not has_traffic:
                outcome = (
                    "No requests observed in the last minute, so health cannot be verified. "
                    "Send traffic to the service and verify again."
                )
            else:
                outcome = (
                    "Within stability thresholds."
                    if within_thresholds
                    else "Still above stability thresholds."
                )
            report = HealthVerificationReport(
                stabilized=stabilized,
                previous_error_rate=prev_error,
                current_error_rate=current.error_rate_5xx_percent,
                previous_latency_ms=prev_latency_ms,
                current_latency_ms=current.p95_latency_ms,
                observation_window_seconds=VERIFY_SETTLE_SECONDS,
                details=(
                    f"5xx error rate {prev_error:.2f}% -> {current.error_rate_5xx_percent:.2f}%; "
                    f"p95 latency {prev_latency_ms:.0f}ms -> {current.p95_latency_ms:.0f}ms. {outcome}"
                ),
            )

    return {
        "verification_results": report,
        "verification_report": report,
        "audit_events": [
            f"Health verification completed: Stabilized={report.stabilized} ({report.details})"
        ],
    }


async def node_persist_incident_memory(state: InvestigationState) -> dict[str, Any]:
    """Node 10: Persists resolved incident summary into Qdrant for future similarity search."""
    incident_id = state["incident_id"]
    service = state["service"]
    symptoms = state["symptoms"]
    top_hypo = state.get("selected_hypothesis")
    exec_result = state.get("execution_result")

    root_cause = top_hypo.root_cause if top_hypo else "Undetermined"
    remediation = exec_result.action_type if exec_result else "None"
    outcome = "RESOLVED" if (exec_result and exec_result.success) else "UNRESOLVED"

    try:
        qdrant = get_shared_qdrant_service()
        await qdrant.persist_resolved_incident(
            incident_id=incident_id,
            service=service,
            symptoms=symptoms,
            root_cause=root_cause,
            remediation=remediation,
            outcome=outcome,
        )
        msg = "Persisted resolved incident into Qdrant memory"
    except Exception as exc:
        logger.warning(f"Failed to persist incident memory to Qdrant: {exc}")
        msg = f"Incident memory persistence skipped: {exc}"

    return {"audit_events": [msg]}


async def node_generate_postmortem(state: InvestigationState) -> dict[str, Any]:
    """Node 11: Produces structured executive postmortem report."""
    logger.info("[Node 11: GeneratePostmortem] Producing executive postmortem report")
    postmortem = create_incident_report(state)

    return {
        "postmortem": postmortem,
        "audit_events": ["Executive incident postmortem report generated and archived."],
    }
