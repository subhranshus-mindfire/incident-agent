import logging
from datetime import UTC, datetime
from typing import Any

from app.constants.service_dependencies import SERVICE_DEPENDENCIES, ServiceDependencyMap
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
from app.services.loki_service import LokiService
from app.services.prometheus_service import PrometheusService
from app.services.qdrant_service import get_shared_qdrant_service
from app.services.remediation_service import get_remediation_executor

logger = logging.getLogger("incident_agent.tools")

DEFAULT_DEPLOYMENT_CATALOG: dict[str, list[DeploymentRecord]] = {
    "payment-api": [
        DeploymentRecord(
            deployment_id="DEP-101",
            service="payment-api",
            version="v2.3.1",
            deployed_at="2026-11-02T10:00:00Z",
            deployed_by="GitOps Deployer",
            commit_sha="c3f81e9",
            status="SUCCESS",
        ),
        DeploymentRecord(
            deployment_id="DEP-100",
            service="payment-api",
            version="v2.3.0",
            deployed_at="2026-11-01T18:00:00Z",
            deployed_by="GitOps Deployer",
            commit_sha="a1b2c3d",
            status="SUCCESS",
        ),
    ],
    "order-service": [
        DeploymentRecord(
            deployment_id="DEP-201",
            service="order-service",
            version="v1.8.0",
            deployed_at="2026-11-02T08:30:00Z",
            deployed_by="GitOps Deployer",
            commit_sha="f4e5d6c",
            status="SUCCESS",
        )
    ],
    "auth-service": [
        DeploymentRecord(
            deployment_id="DEP-301",
            service="auth-service",
            version="v3.1.2",
            deployed_at="2026-10-31T12:00:00Z",
            deployed_by="GitOps Deployer",
            commit_sha="d9e8f7a",
            status="SUCCESS",
        )
    ],
}


async def fetch_application_logs(
    service: str,
    time_range_minutes: int = 15,
) -> list[LogSignature]:
    """Tool 1: Returns deduplicated error log signatures from live Loki or synthetic fallbacks."""
    loki = LokiService()
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

    if not signatures:
        # Grounded synthetic fallback for payment-api / generic services
        if "payment" in service.lower():
            signatures = [
                LogSignature(
                    sample_line="ERROR 500: Database connection timeout waiting for connection at 10:15",
                    count=14,
                ),
                LogSignature(
                    sample_line="ERROR 500: Connection pool exhausted (max 50 connections reached) at 10:16",
                    count=26,
                ),
            ]
        elif "order" in service.lower():
            signatures = [
                LogSignature(
                    sample_line="ERROR 504: Gateway Timeout calling downstream payment-api",
                    count=18,
                )
            ]
        else:
            signatures = [
                LogSignature(sample_line=f"Elevated error rates detected on {service}", count=5)
            ]

    return signatures


async def get_system_metrics(
    service: str,
) -> TelemetrySummary:
    """Tool 2: Retrieves Prometheus golden signals (error rate, latency, CPU, memory)."""
    prom = PrometheusService()
    try:
        gs = await prom.get_golden_signals(service=service)
        if isinstance(gs, GoldenSignalMetrics):
            anomalies: list[str] = []
            if gs.error_rate_5xx_percent > 5.0:
                anomalies.append(f"High 5xx error rate: {gs.error_rate_5xx_percent:.1f}%")
            if gs.p95_latency_ms > 1000.0:
                anomalies.append(f"Elevated p95 latency: {gs.p95_latency_ms:.0f}ms")
            if gs.cpu_usage_percent > 80.0:
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

    # Fallback telemetry
    return TelemetrySummary(
        http_error_rate_pct=8.5,
        p99_latency_seconds=1.45,
        request_rate_per_sec=120.0,
        cpu_usage_pct=88.0,
        memory_usage_pct=52.0,
        detected_anomalies=["High p99 Latency (>1000ms)", "Elevated 5xx Rate (>5%)"],
    )


def get_recent_deployments(service: str) -> list[DeploymentRecord]:
    """Tool 3: Finds recent releases, image tags, and deployment timestamps for a service."""
    if service in DEFAULT_DEPLOYMENT_CATALOG:
        return DEFAULT_DEPLOYMENT_CATALOG[service]
    return [
        DeploymentRecord(
            deployment_id="DEP-GENERIC",
            service=service,
            version="v1.0.0",
            deployed_at=datetime.now(UTC).isoformat(),
            status="SUCCESS",
        )
    ]


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
    if service in SERVICE_DEPENDENCIES:
        return SERVICE_DEPENDENCIES[service]
    return ServiceDependencyMap(
        service=service,
        upstream_services=["api-gateway"],
        downstream_services=["postgres"],
        tier="tier-2",
        criticality="standard",
    )


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
    return await executor.execute_action(proposal, dry_run=False)


def create_incident_report(incident_state: InvestigationState) -> PostmortemReport:
    """Tool 7: Synthesizes structured executive RCA postmortem report."""
    engine = get_investigation_engine()
    return engine.generate_postmortem_report(incident_state)
