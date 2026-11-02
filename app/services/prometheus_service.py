import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config.config import settings
from app.exceptions.domain import ExternalServiceException
from app.schemas.telemetry import (
    AnomalyAlert,
    GoldenSignalMetrics,
    MetricPoint,
    MetricQueryResult,
    MetricSeries,
)

logger = logging.getLogger("incident_agent.prometheus_service")


class PrometheusService:
    """Production client for querying Prometheus metrics with retries, pooling, and SRE signals."""

    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 8.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = (base_url or settings.PROMETHEUS_URL).rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds, connect=4.0)
        self.max_retries = max_retries
        self._external_client = client
        self._client: httpx.AsyncClient | None = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and self._external_client is None:
            await self._client.aclose()
            self._client = None

    async def _execute_with_retry(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.get(endpoint, params=params)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        res_data = data.get("data", {})
                        return res_data if isinstance(res_data, dict) else {}
                    raise ExternalServiceException(
                        service_name="Prometheus",
                        message=f"Query error from Prometheus API: {data.get('error', 'unknown')}",
                    )
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Server error {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                raise ExternalServiceException(
                    service_name="Prometheus",
                    message=f"HTTP {response.status_code}: {response.text[:200]}",
                )
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = 0.3 * (2 ** (attempt - 1))
                    logger.warning(
                        "Prometheus query '%s' failed (attempt %d/%d). Retrying in %.2fs: %s",
                        params.get("query"),
                        attempt,
                        self.max_retries,
                        backoff,
                        exc,
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error("Prometheus query exhausted retries: %s", exc)

        raise ExternalServiceException(
            service_name="Prometheus",
            message=f"Failed to query Prometheus after {self.max_retries} attempts: {last_error}",
        )

    def _parse_metric_result(self, query: str, data: dict[str, Any]) -> MetricQueryResult:
        result_type = data.get("resultType", "unknown")
        raw_results = data.get("result", [])
        series_list: list[MetricSeries] = []

        if result_type == "vector":
            for item in raw_results:
                metric_labels = item.get("metric", {})
                metric_name = metric_labels.get("__name__", "")
                val_tuple = item.get("value", [0, "0"])
                try:
                    ts = datetime.fromtimestamp(float(val_tuple[0]), tz=UTC)
                    val = float(val_tuple[1])
                except (ValueError, IndexError):
                    continue

                series_list.append(
                    MetricSeries(
                        metric_name=metric_name,
                        labels=metric_labels,
                        points=[MetricPoint(timestamp=ts, value=val)],
                    )
                )

        elif result_type == "matrix":
            for item in raw_results:
                metric_labels = item.get("metric", {})
                metric_name = metric_labels.get("__name__", "")
                points: list[MetricPoint] = []
                for pt in item.get("values", []):
                    try:
                        ts = datetime.fromtimestamp(float(pt[0]), tz=UTC)
                        val = float(pt[1])
                        points.append(MetricPoint(timestamp=ts, value=val))
                    except (ValueError, IndexError):
                        continue

                series_list.append(
                    MetricSeries(
                        metric_name=metric_name,
                        labels=metric_labels,
                        points=points,
                    )
                )

        return MetricQueryResult(query=query, result_type=result_type, series=series_list)

    async def query(self, promql: str, time: datetime | None = None) -> MetricQueryResult:
        """Executes an instant PromQL query at a given evaluation timestamp."""
        params: dict[str, Any] = {"query": promql}
        if time:
            params["time"] = time.timestamp()

        data = await self._execute_with_retry("/api/v1/query", params)
        return self._parse_metric_result(promql, data)

    async def query_range(
        self,
        promql: str,
        start: datetime,
        end: datetime,
        step: str = "15s",
    ) -> MetricQueryResult:
        """Executes a PromQL range query over a specified time window."""
        params: dict[str, Any] = {
            "query": promql,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step,
        }
        data = await self._execute_with_retry("/api/v1/query_range", params)
        return self._parse_metric_result(promql, data)

    async def _query_single_value(self, promql: str, default: float = 0.0) -> float:
        """Helper to extract a single scalar/vector value safely."""
        try:
            res = await self.query(promql)
            if res.series and res.series[0].points:
                val = res.series[0].points[0].value
                # Filter out NaN / Inf
                if val != val or val == float("inf") or val == float("-inf"):
                    return default
                return val
        except Exception as ex:
            logger.debug("Metric query failed or returned no data (%s): %s", promql, ex)
        return default

    async def get_golden_signals(
        self,
        service: str,
        window_minutes: int = 15,
    ) -> GoldenSignalMetrics:
        """Computes Google SRE Golden Signals for a given service."""
        window = f"{window_minutes}m"

        # Queries for Golden Signals
        err_query = (
            f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[{window}])) '
            f'/ (sum(rate(http_requests_total{{service="{service}"}}[{window}])) + 0.0001) * 100'
        )
        rate_query = f'sum(rate(http_requests_total{{service="{service}"}}[{window}]))'
        lat_query = f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{service="{service}"}}[{window}])) by (le)) * 1000'
        cpu_query = f'avg(rate(container_cpu_usage_seconds_total{{container="{service}",container!=""}}[{window}])) * 100'
        mem_query = (
            f'sum(container_memory_working_set_bytes{{container="{service}"}}) '
            f'/ (sum(container_spec_memory_limit_bytes{{container="{service}"}}) + 1) * 100'
        )

        error_rate, req_rate, p95_lat, cpu_pct, mem_pct = await asyncio.gather(
            self._query_single_value(err_query, default=0.0),
            self._query_single_value(rate_query, default=0.0),
            self._query_single_value(lat_query, default=0.0),
            self._query_single_value(cpu_query, default=0.0),
            self._query_single_value(mem_query, default=0.0),
        )

        return GoldenSignalMetrics(
            service=service,
            error_rate_5xx_percent=round(max(0.0, error_rate), 2),
            request_rate_per_sec=round(max(0.0, req_rate), 2),
            p95_latency_ms=round(max(0.0, p95_lat), 2),
            cpu_usage_percent=round(max(0.0, min(100.0, cpu_pct)), 2),
            memory_usage_percent=round(max(0.0, min(100.0, mem_pct)), 2),
            collected_at=datetime.now(UTC),
        )

    async def detect_anomalies(
        self,
        service: str,
        window_minutes: int = 15,
    ) -> list[AnomalyAlert]:
        """Detects threshold breaches across SRE golden signals."""
        signals = await self.get_golden_signals(service, window_minutes)
        anomalies: list[AnomalyAlert] = []

        # 1. 5xx Error Rate Check (>5% warning, >15% critical)
        if signals.error_rate_5xx_percent >= 5.0:
            severity = "critical" if signals.error_rate_5xx_percent >= 15.0 else "warning"
            anomalies.append(
                AnomalyAlert(
                    metric_name="http_5xx_error_rate",
                    current_value=signals.error_rate_5xx_percent,
                    baseline_value=0.5,
                    threshold_value=5.0,
                    is_breached=True,
                    severity=severity,
                    message=f"HTTP 5xx error rate is elevated at {signals.error_rate_5xx_percent}% (threshold: 5.0%)",
                )
            )

        # 2. P95 Latency Check (>1000ms warning, >3000ms critical)
        if signals.p95_latency_ms >= 1000.0:
            severity = "critical" if signals.p95_latency_ms >= 3000.0 else "warning"
            anomalies.append(
                AnomalyAlert(
                    metric_name="p95_request_latency_ms",
                    current_value=signals.p95_latency_ms,
                    baseline_value=150.0,
                    threshold_value=1000.0,
                    is_breached=True,
                    severity=severity,
                    message=f"P95 latency spiked to {signals.p95_latency_ms}ms (threshold: 1000ms)",
                )
            )

        # 3. CPU Saturation (>85% warning, >95% critical)
        if signals.cpu_usage_percent >= 85.0:
            severity = "critical" if signals.cpu_usage_percent >= 95.0 else "warning"
            anomalies.append(
                AnomalyAlert(
                    metric_name="cpu_usage_percent",
                    current_value=signals.cpu_usage_percent,
                    baseline_value=30.0,
                    threshold_value=85.0,
                    is_breached=True,
                    severity=severity,
                    message=f"CPU utilization is at {signals.cpu_usage_percent}% (threshold: 85.0%)",
                )
            )

        # 4. Memory Saturation (>85% warning, >95% critical)
        if signals.memory_usage_percent >= 85.0:
            severity = "critical" if signals.memory_usage_percent >= 95.0 else "warning"
            anomalies.append(
                AnomalyAlert(
                    metric_name="memory_usage_percent",
                    current_value=signals.memory_usage_percent,
                    baseline_value=45.0,
                    threshold_value=85.0,
                    is_breached=True,
                    severity=severity,
                    message=f"Memory utilization is at {signals.memory_usage_percent}% (threshold: 85.0%)",
                )
            )

        return anomalies

    async def health_check(self) -> bool:
        """Returns True if the Prometheus server is reachable and healthy."""
        try:
            client = await self._get_client()
            res = await client.get("/-/healthy")
            return res.status_code == 200
        except Exception:
            return False
