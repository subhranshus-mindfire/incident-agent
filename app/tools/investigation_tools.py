import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from app.constants.service_dependencies import SERVICE_DEPENDENCIES, ServiceDependencyMap
from app.constants.services import PRIMARY_SERVICE
from app.constants.thresholds import (
    CPU_CRITICAL_PCT,
    ERROR_RATE_CRITICAL_PCT,
    LATENCY_FAULT_MS,
)
from app.llms.llm_engine import get_investigation_engine
from app.schemas.agent_state import (
    DeploymentRecord,
    HistoricalIncident,
    InvestigationState,
    LogSignature,
    PostmortemReport,
    RemediationActionType,
    RemediationExecutionResult,
    RemediationProposal,
    RiskTier,
    TelemetrySummary,
)
from app.schemas.telemetry import GoldenSignalMetrics, LogQueryResult
from app.services.clients import get_loki_service, get_prometheus_service
from app.services.qdrant_service import get_shared_qdrant_service
from app.services.remediation_service import get_remediation_executor

logger = logging.getLogger("incident_agent.tools")


async def fetch_application_logs(
    service: str,
    time_range_minutes: int = 15,
) -> list[LogSignature]:
    """Tool 1: Returns deduplicated error log signatures from live Loki. Empty means none were found."""
    loki = get_loki_service()
    now = datetime.now(UTC)
    start_time = datetime.fromtimestamp(now.timestamp() - (time_range_minutes * 60), tz=UTC)

    signatures: list[LogSignature] = []
    try:
        query_res = await loki.query_range(
            f'{{service="{service}"}} |= "error"',
            start=start_time,
            end=now,
            limit=50,
        )
        if isinstance(query_res, LogQueryResult) and query_res.streams:
            for stream in query_res.streams:
                for entry in stream.entries[:5]:
                    signatures.append(
                        LogSignature(sample_line=entry.line[:250], count=entry.dedup_count)
                    )
    except Exception as exc:
        logger.warning(f"Loki fetch failed: {exc}")

    return signatures


async def get_system_metrics(
    service: str,
) -> TelemetrySummary:
    """Tool 2: Retrieves Prometheus golden signals (error rate, latency, CPU, memory)."""
    prom = get_prometheus_service()
    try:
        gs = await prom.get_golden_signals(service=service)
        if isinstance(gs, GoldenSignalMetrics):
            anomalies: list[str] = []
            if gs.error_rate_5xx_percent > ERROR_RATE_CRITICAL_PCT:
                anomalies.append(f"High 5xx error rate: {gs.error_rate_5xx_percent:.1f}%")
            if gs.p95_latency_ms > LATENCY_FAULT_MS:
                anomalies.append(f"Elevated p95 latency: {gs.p95_latency_ms:.0f}ms")
            if gs.cpu_usage_percent > CPU_CRITICAL_PCT:
                anomalies.append(f"Severe CPU saturation: {gs.cpu_usage_percent:.1f}%")

            return TelemetrySummary(
                http_error_rate_pct=gs.error_rate_5xx_percent,
                p99_latency_seconds=round(gs.p95_latency_ms / 1000.0, 3),
                request_rate_per_sec=gs.request_rate_per_sec,
                cpu_usage_pct=gs.cpu_usage_percent,
                memory_usage_pct=gs.memory_usage_percent,
                detected_anomalies=anomalies,
            )
    except Exception as exc:
        logger.warning(f"Prometheus fetch failed: {exc}")

    # Metrics were not measured. Report that instead of inventing a healthy or failing baseline.
    return TelemetrySummary(
        http_error_rate_pct=0.0,
        p99_latency_seconds=0.0,
        request_rate_per_sec=0.0,
        cpu_usage_pct=0.0,
        memory_usage_pct=0.0,
        detected_anomalies=["Prometheus unavailable: metrics not measured"],
    )


async def get_recent_deployments(service: str) -> list[DeploymentRecord]:
    """Tool 3: Finds recent releases, image tags, and deployment timestamps for a service."""
    if service == PRIMARY_SERVICE:
        target_url = os.getenv("PAYMENT_API_URL", "http://payment-api:8080")
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{target_url}/deployments")
                if res.status_code == 200:
                    data = res.json()
                    return [
                        DeploymentRecord(
                            deployment_id=d["deployment_id"],
                            service=PRIMARY_SERVICE,
                            version=d["version"],
                            deployed_at=d["deployed_at"],
                            commit_sha=d.get("commit_sha", "unknown"),
                            status=d.get("status", "UNKNOWN"),
                        )
                        for d in data
                    ]
        except Exception as exc:
            logger.debug(f"Live deployment fetch from payment-api failed: {exc}")

    # No deployment API record: report none rather than a placeholder.
    return []


async def search_past_incidents(
    query: str,
    service: str | None = None,
    limit: int = 3,
) -> list[HistoricalIncident]:
    """Tool 4: Semantic Qdrant vector search over historical incident memory."""
    qdrant = get_shared_qdrant_service()
    return await qdrant.search_historical_incidents(query=query, service=service, limit=limit)


def get_service_dependencies(service: str) -> ServiceDependencyMap:
    """Tool 5: Identifies upstream and downstream dependencies and architectural impact."""
    # Unknown services get an empty map, not invented dependencies.
    if service in SERVICE_DEPENDENCIES:
        return SERVICE_DEPENDENCIES[service]
    return ServiceDependencyMap(service=service, tier="unknown", criticality="unknown")


async def execute_remediation(
    action: str,
    service: str,
    approval_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> RemediationExecutionResult:
    """Tool 6: Executes a whitelisted, idempotent mock or live remediation action."""
    executor = get_remediation_executor()
    try:
        action_type = RemediationActionType(action)
    except ValueError:
        action_type = RemediationActionType.MANUAL_ESCALATION

    proposal = RemediationProposal(
        action_type=action_type,
        target_resource=f"deployment/{service}",
        parameters=parameters or {},
        risk_tier=RiskTier.LOW if "SCALE" in action else RiskTier.CRITICAL,
        blast_radius=f"Remediation on {service} (approval_id={approval_id})",
        rollback_plan=f"Revert action {action} on {service}",
        requires_approval=approval_id is None,
    )

    # payment-api is the live target: success is only reported once its health confirms the fix.
    if service == PRIMARY_SERVICE:
        return await _apply_payment_api_remediation(action_type)

    return await executor.execute_action(proposal, dry_run=False)


# Remediation endpoint on payment-api for each action.
_PAYMENT_API_REMEDIATIONS: dict[RemediationActionType, str] = {
    RemediationActionType.ROLLBACK_DEPLOYMENT: "/remediation/rollback",
    RemediationActionType.TERMINATE_DB_TRANSACTIONS: "/remediation/kill-queries",
    RemediationActionType.ROLLING_RESTART: "/remediation/restart",
}

# Which remediation clears each live fault that payment-api reports on /health.
FAULT_REMEDIATIONS: dict[str, RemediationActionType] = {
    "bad_deployment": RemediationActionType.ROLLBACK_DEPLOYMENT,
    "deadlock": RemediationActionType.TERMINATE_DB_TRANSACTIONS,
    "cpu_burn": RemediationActionType.ROLLING_RESTART,
}


async def get_active_faults(service: str) -> dict[str, bool] | None:
    """Fault flags payment-api reports right now. None when the service cannot be reached."""
    if service != PRIMARY_SERVICE:
        return None
    target_url = os.getenv("PAYMENT_API_URL", "http://payment-api:8080")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{target_url}/health")
            res.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"payment-api health probe failed: {exc}")
        return None
    return {name: bool(on) for name, on in res.json().get("active_chaos", {}).items()}


async def _apply_payment_api_remediation(
    action_type: RemediationActionType,
) -> RemediationExecutionResult:
    """Calls payment-api's remediation endpoint and checks its health before reporting success."""
    if action_type not in _PAYMENT_API_REMEDIATIONS:
        return RemediationExecutionResult(
            success=False,
            action_type=action_type.value,
            message=f"No payment-api remediation exists for {action_type.value}.",
        )

    endpoint = _PAYMENT_API_REMEDIATIONS[action_type]
    target_url = os.getenv("PAYMENT_API_URL", "http://payment-api:8080")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            applied = await client.post(f"{target_url}{endpoint}")
            applied.raise_for_status()
            health = await client.get(f"{target_url}/health")
            health.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error(f"payment-api rejected {action_type.value}: {exc}")
        return RemediationExecutionResult(
            success=False,
            action_type=action_type.value,
            message=f"payment-api did not apply {action_type.value}: {exc}",
        )

    # Success means every fault is gone, not just the one this action targets.
    chaos = health.json().get("active_chaos", {})
    still_active = [name for name, on in chaos.items() if on]
    if still_active:
        hints = ", ".join(
            f"{name} needs {FAULT_REMEDIATIONS[name].value}"
            for name in still_active
            if name in FAULT_REMEDIATIONS
        )
        return RemediationExecutionResult(
            success=False,
            action_type=action_type.value,
            message=(
                f"{action_type.value} applied, but payment-api still reports: {', '.join(still_active)}. "
                f"{hints}."
            ),
            stdout=applied.text,
        )

    return RemediationExecutionResult(
        success=True,
        action_type=action_type.value,
        message=f"{action_type.value} applied; payment-api health reports no active faults.",
        stdout=applied.text,
    )


def create_incident_report(incident_state: InvestigationState) -> PostmortemReport:
    """Tool 7: Synthesizes structured executive RCA postmortem report."""
    engine = get_investigation_engine()
    return engine.generate_postmortem_report(incident_state)
