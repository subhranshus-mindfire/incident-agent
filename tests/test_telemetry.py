from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.exceptions.domain import ExternalServiceException
from app.schemas.telemetry import LogEntry
from app.services.loki_service import LokiService
from app.services.prometheus_service import PrometheusService


@pytest.fixture
def mock_prometheus_vector_response() -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {
                        "__name__": "http_requests_total",
                        "service": "payment-service",
                        "status": "200",
                    },
                    "value": [1700000000.0, "1542.5"],
                }
            ],
        },
    }


@pytest.fixture
def mock_prometheus_matrix_response() -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {
                        "__name__": "container_cpu_usage_seconds_total",
                        "container": "payment-service",
                    },
                    "values": [
                        [1700000000.0, "0.45"],
                        [1700000015.0, "0.55"],
                        [1700000030.0, "0.92"],
                    ],
                }
            ],
        },
    }


@pytest.fixture
def mock_loki_stream_response() -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"service": "payment-service", "namespace": "prod"},
                    "values": [
                        [
                            "1700000000000000000",
                            "ERROR [payment-service] Connection timeout to database at 10.0.1.5:5432",
                        ],
                        [
                            "1700000001000000000",
                            "ERROR [payment-service] Connection timeout to database at 10.0.1.5:5432",
                        ],
                        [
                            "1700000002000000000",
                            "ERROR [payment-service] Failed transaction for user 9482 with Authorization: Bearer secret-token-xyz123",
                        ],
                    ],
                }
            ],
        },
    }


@pytest.mark.asyncio
async def test_prometheus_query_instant_vector(mock_prometheus_vector_response: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/v1/query" in str(request.url)
        return httpx.Response(200, json=mock_prometheus_vector_response)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://mock-prometheus:9090")
    service = PrometheusService(client=client)

    result = await service.query("http_requests_total")
    assert result.status == "success"
    assert result.result_type == "vector"
    assert len(result.series) == 1
    assert result.series[0].metric_name == "http_requests_total"
    assert result.series[0].points[0].value == 1542.5


@pytest.mark.asyncio
async def test_prometheus_query_range_matrix(mock_prometheus_matrix_response: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/v1/query_range" in str(request.url)
        return httpx.Response(200, json=mock_prometheus_matrix_response)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://mock-prometheus:9090")
    service = PrometheusService(client=client)

    start = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    end = datetime(2023, 11, 14, 22, 13, 50, tzinfo=UTC)
    result = await service.query_range("container_cpu_usage_seconds_total", start=start, end=end)

    assert result.result_type == "matrix"
    assert len(result.series) == 1
    assert len(result.series[0].points) == 3
    assert result.series[0].points[-1].value == 0.92


@pytest.mark.asyncio
async def test_prometheus_golden_signals_and_anomalies():
    def handler(request: httpx.Request) -> httpx.Response:
        promql = str(request.url.params.get("query", ""))
        val = "0.0"
        if "5.." in promql:
            val = "18.5"  # 18.5% 5xx error rate (critical!)
        elif "quantile" in promql:
            val = "3500.0"  # 3500ms latency (critical!)
        elif "cpu" in promql:
            val = "96.5"  # 96.5% CPU (critical!)
        elif "memory" in promql:
            val = "60.0"
        elif "rate(" in promql:
            val = "250.0"  # 250 req/s

        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1700000000.0, val]}],
                },
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://mock-prometheus:9090")
    service = PrometheusService(client=client)

    signals = await service.get_golden_signals("checkout-service")
    assert signals.service == "checkout-service"
    assert signals.error_rate_5xx_percent == 18.5
    assert signals.p95_latency_ms == 3500.0
    assert signals.cpu_usage_percent == 96.5

    anomalies = await service.detect_anomalies("checkout-service")
    assert len(anomalies) >= 3
    criticals = [a for a in anomalies if a.severity == "critical"]
    assert len(criticals) >= 3


@pytest.mark.asyncio
async def test_prometheus_retries_and_failure():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"resultType": "vector", "result": []},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://mock-prometheus:9090")
    service = PrometheusService(client=client, max_retries=3)

    result = await service.query("up")
    assert result.status == "success"
    assert attempts == 3


@pytest.mark.asyncio
async def test_prometheus_max_retries_exhausted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://mock-prometheus:9090")
    service = PrometheusService(client=client, max_retries=2)

    with pytest.raises(ExternalServiceException) as exc_info:
        await service.query("up")
    assert "Failed to query Prometheus" in str(exc_info.value)


@pytest.mark.asyncio
async def test_loki_secret_redaction():
    service = LokiService()

    raw_log = (
        "User authenticated with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-ID123 "
        'and secret password="supersecretpassword123" with AWS key AKIAIOSFODNN7EXAMPLE'
    )
    redacted = service.redact_secrets(raw_log)

    assert "supersecretpassword123" not in redacted
    assert "Bearer [REDACTED_TOKEN]" in redacted or "[REDACTED_JWT]" in redacted
    assert "[REDACTED_AWS_KEY]" in redacted
    assert 'password="[REDACTED]"' in redacted or "password=[REDACTED]" in redacted


@pytest.mark.asyncio
async def test_loki_log_deduplication():
    service = LokiService()

    now = datetime.now(UTC)
    entries = [
        LogEntry(
            timestamp=now, line="Connection timeout to redis:6379 after 5000ms", level="ERROR"
        ),
        LogEntry(
            timestamp=now, line="Connection timeout to redis:6379 after 5000ms", level="ERROR"
        ),
        LogEntry(
            timestamp=now, line="Connection timeout to redis:6379 after 5000ms", level="ERROR"
        ),
        LogEntry(timestamp=now, line="Different distinct error occurred", level="ERROR"),
    ]

    deduped = service.deduplicate_logs(entries)
    assert len(deduped) == 2
    timeout_entry = next(e for e in deduped if "Connection timeout" in e.line)
    assert timeout_entry.dedup_count == 3


@pytest.mark.asyncio
async def test_loki_token_budget_truncation():
    service = LokiService(max_line_length=100)

    long_line = "A" * 300
    truncated = service._truncate_line(long_line)
    assert len(truncated) <= 125
    assert truncated.endswith("... [TRUNCATED]")


@pytest.mark.asyncio
async def test_loki_query_range(mock_loki_stream_response: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/loki/api/v1/query_range" in str(request.url)
        return httpx.Response(200, json=mock_loki_stream_response)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://mock-loki:3100")
    service = LokiService(client=client)

    start = datetime(2023, 11, 14, 22, 0, 0, tzinfo=UTC)
    end = datetime(2023, 11, 14, 22, 15, 0, tzinfo=UTC)
    result = await service.query_range('{service="payment-service"}', start=start, end=end)

    assert result.status == "success"
    assert result.total_lines_scanned == 3
    # 2 timeout errors were deduplicated into 1
    assert result.returned_lines == 2
    stream = result.streams[0]
    timeout_entry = next(e for e in stream.entries if "Connection timeout" in e.line)
    assert timeout_entry.dedup_count == 2
    auth_entry = next(e for e in stream.entries if "secret-token" not in e.line)
    assert "[REDACTED_TOKEN]" in auth_entry.line or "[REDACTED]" in auth_entry.line


@pytest.mark.asyncio
async def test_telemetry_api_routes(client: httpx.AsyncClient):
    # Test Prometheus health probe via API
    res = await client.get("/api/v1/telemetry/health")
    assert res.status_code == 200
    data = res.json()
    assert "prometheus" in data
    assert "loki" in data
    assert "timestamp" in data
