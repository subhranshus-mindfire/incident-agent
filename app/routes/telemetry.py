import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, status

from app.schemas.telemetry import (
    AnomalyAlert,
    GoldenSignalMetrics,
    LogEntry,
    LogQueryResult,
    MetricQueryResult,
)
from app.services.clients import get_loki_service, get_prometheus_service
from app.services.loki_service import LokiService
from app.services.prometheus_service import PrometheusService

logger = logging.getLogger("incident_agent.routes.telemetry")
router = APIRouter(prefix="/telemetry", tags=["Observability & Telemetry"])

SERVICE_QUERY_PARAM = Query(
    ...,
    min_length=1,
    max_length=128,
    pattern=r"^[a-zA-Z0-9_\-\.]+$",
    description="Target service identifier (alphanumeric, dash, dot, underscore only)",
    examples=["checkout-service"],
)


@router.get("/metrics/query", response_model=MetricQueryResult, status_code=status.HTTP_200_OK)
async def query_prometheus_metrics(
    query: str = Query(..., description="PromQL query expression"),
    prom_service: PrometheusService = Depends(get_prometheus_service),
) -> MetricQueryResult:
    """Executes an instant PromQL metric query against Prometheus."""
    return await prom_service.query(promql=query)


@router.get(
    "/metrics/golden-signals",
    response_model=GoldenSignalMetrics,
    status_code=status.HTTP_200_OK,
)
async def get_service_golden_signals(
    service: str = SERVICE_QUERY_PARAM,
    window_minutes: int = Query(15, ge=1, le=120, description="Evaluation window in minutes"),
    window_seconds: int | None = Query(
        None,
        ge=10,
        le=7200,
        description="Short live window in seconds (overrides window_minutes; min 10)",
    ),
    prom_service: PrometheusService = Depends(get_prometheus_service),
) -> GoldenSignalMetrics:
    """Computes Google SRE Golden Signals (Error rate, Throughput, Latency, Saturation) for a service."""
    return await prom_service.get_golden_signals(
        service=service, window_minutes=window_minutes, window_seconds=window_seconds
    )


@router.get(
    "/metrics/anomalies",
    response_model=list[AnomalyAlert],
    status_code=status.HTTP_200_OK,
)
async def detect_service_anomalies(
    service: str = SERVICE_QUERY_PARAM,
    window_minutes: int = Query(15, ge=1, le=120, description="Evaluation window in minutes"),
    prom_service: PrometheusService = Depends(get_prometheus_service),
) -> list[AnomalyAlert]:
    """Detects metric threshold anomalies and severity across service golden signals."""
    return await prom_service.detect_anomalies(service=service, window_minutes=window_minutes)


@router.get("/logs/query", response_model=LogQueryResult, status_code=status.HTTP_200_OK)
async def query_loki_logs(
    query: str = Query(..., description="LogQL query expression"),
    window_minutes: int = Query(15, ge=1, le=120, description="Time window in minutes"),
    window_seconds: int | None = Query(
        None, ge=1, le=7200, description="Short live window in seconds (overrides window_minutes)"
    ),
    limit: int = Query(100, ge=1, le=500, description="Maximum raw lines to scan"),
    deduplicate: bool = Query(True, description="Cluster and deduplicate recurring error lines"),
    loki_service: LokiService = Depends(get_loki_service),
) -> LogQueryResult:
    """Queries Grafana Loki logs with automatic secret redaction and log deduplication."""
    end = datetime.now(UTC)
    span_seconds = window_seconds or window_minutes * 60
    start = datetime.fromtimestamp(end.timestamp() - span_seconds, tz=UTC)
    return await loki_service.query_range(
        logql=query,
        start=start,
        end=end,
        limit=limit,
        deduplicate=deduplicate,
    )


@router.get("/logs/errors", response_model=list[LogEntry], status_code=status.HTTP_200_OK)
async def get_service_error_logs(
    service: str = SERVICE_QUERY_PARAM,
    window_minutes: int = Query(15, ge=1, le=120, description="Time window in minutes"),
    max_entries: int = Query(50, ge=1, le=200, description="Maximum error entries to return"),
    loki_service: LokiService = Depends(get_loki_service),
) -> list[LogEntry]:
    """Retrieves critical error logs for a service, sanitized of secrets and deduplicated."""
    return await loki_service.get_service_errors(
        service=service,
        window_minutes=window_minutes,
        max_entries=max_entries,
    )


@router.get("/health", response_model=dict[str, Any], status_code=status.HTTP_200_OK)
async def telemetry_health_probes(
    prom_service: PrometheusService = Depends(get_prometheus_service),
    loki_service: LokiService = Depends(get_loki_service),
) -> dict[str, Any]:
    """Liveness probe inspecting connectivity to Prometheus and Loki backends."""
    prom_healthy = await prom_service.health_check()
    loki_healthy = await loki_service.health_check()
    return {
        "prometheus": "healthy" if prom_healthy else "unreachable",
        "loki": "healthy" if loki_healthy else "unreachable",
        "timestamp": datetime.now(UTC).isoformat(),
    }
