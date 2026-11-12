import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis import Redis
from redis.exceptions import RedisError

from app.schemas.telemetry import GoldenSignalMetrics, LogQueryResult
from app.services import prometheus_service as prom_module
from app.services.prometheus_service import PrometheusService
from app.utils.cache import RedisCache

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")


def _reachable() -> bool:
    try:
        return bool(Redis.from_url(TEST_REDIS_URL, socket_connect_timeout=0.5).ping())
    except RedisError:
        return False


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.values[key] = value


def _signals(service: str) -> GoldenSignalMetrics:
    return GoldenSignalMetrics(
        service=service,
        error_rate_5xx_percent=0.0,
        request_rate_per_sec=5.0,
        p95_latency_ms=120.0,
        cpu_usage_percent=12.0,
        memory_usage_percent=30.0,
        window_seconds=60,
        collected_at=datetime.now(UTC),
    )


@pytest.fixture
def counting_service(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"count": 0}

    async def fake_compute(self, safe_service, window_minutes, window_seconds):
        calls["count"] += 1
        return _signals(safe_service)

    monkeypatch.setattr(PrometheusService, "_compute_golden_signals", fake_compute)
    return calls


async def test_chat_reads_within_ttl_are_served_from_cache(
    monkeypatch: pytest.MonkeyPatch, counting_service: dict[str, int]
) -> None:
    fake = _MemoryCache()
    monkeypatch.setattr(prom_module, "get_cache", lambda: fake)
    service = PrometheusService(base_url="http://prom.invalid")

    first = await service.get_golden_signals("payment-api", window_seconds=60, use_cache=True)
    second = await service.get_golden_signals("payment-api", window_seconds=60, use_cache=True)

    assert counting_service["count"] == 1
    assert second.model_dump() == first.model_dump()


async def test_investigation_reads_bypass_the_cache(
    monkeypatch: pytest.MonkeyPatch, counting_service: dict[str, int]
) -> None:
    fake = _MemoryCache()
    monkeypatch.setattr(prom_module, "get_cache", lambda: fake)
    service = PrometheusService(base_url="http://prom.invalid")

    await service.get_golden_signals("payment-api", window_seconds=60, use_cache=True)
    await service.get_golden_signals("payment-api", window_seconds=60)  # verification or severity

    assert counting_service["count"] == 2


async def test_cache_is_off_when_settings_turn_it_off(
    monkeypatch: pytest.MonkeyPatch, counting_service: dict[str, int]
) -> None:
    monkeypatch.setattr(prom_module, "get_cache", lambda: None)
    service = PrometheusService(base_url="http://prom.invalid")

    await service.get_golden_signals("payment-api", window_seconds=60, use_cache=True)
    await service.get_golden_signals("payment-api", window_seconds=60, use_cache=True)

    assert counting_service["count"] == 2


@pytest.mark.skipif(not _reachable(), reason="no Redis server reachable at TEST_REDIS_URL")
async def test_redis_cache_round_trip_and_expiry() -> None:
    cache = RedisCache(TEST_REDIS_URL)
    key = f"test:{uuid.uuid4().hex}"

    await cache.set(key, '{"a": 1}', ttl_seconds=1)
    assert await cache.get(key) == '{"a": 1}'

    await asyncio.sleep(1.1)
    assert await cache.get(key) is None


async def test_unreachable_redis_is_a_cache_miss() -> None:
    cache = RedisCache("redis://127.0.0.1:1/0")

    await cache.set("k", "v", ttl_seconds=5)  # must not raise
    assert await cache.get("k") is None


def _log_result(logql: str, line: str) -> "LogQueryResult":
    from app.schemas.telemetry import LogEntry, LogQueryResult, LogStream

    entry = LogEntry(timestamp=datetime.now(UTC), line=line, level="ERROR")
    return LogQueryResult(
        query=logql,
        total_lines_scanned=1,
        returned_lines=1,
        streams=[LogStream(labels={}, entries=[entry])],
    )


async def test_chat_log_reads_within_the_interval_share_one_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import loki_service as loki_module
    from app.services.loki_service import LokiService

    calls = {"count": 0}
    fake = _MemoryCache()

    async def fake_query(self, logql, start, end, limit, deduplicate):
        calls["count"] += 1
        return _log_result(logql, "payment failed")

    monkeypatch.setattr(LokiService, "_query_range_uncached", fake_query)
    monkeypatch.setattr(loki_module, "get_cache", lambda: fake)
    service = LokiService(base_url="http://loki.invalid")
    selector = '{service="payment-api"}'

    # Both ends fall in the same 10-second bucket and the windows have the same width.
    first_end = datetime(2026, 11, 12, 5, 0, 2, tzinfo=UTC)
    second_end = datetime(2026, 11, 12, 5, 0, 5, tzinfo=UTC)
    await service.query_range(
        selector, first_end - timedelta(seconds=60), first_end, use_cache=True
    )
    second = await service.query_range(
        selector, second_end - timedelta(seconds=60), second_end, use_cache=True
    )

    assert calls["count"] == 1
    assert second.streams[0].entries[0].line == "payment failed"


async def test_investigation_log_reads_bypass_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import loki_service as loki_module
    from app.services.loki_service import LokiService

    calls = {"count": 0}
    fake = _MemoryCache()

    async def fake_query(self, logql, start, end, limit, deduplicate):
        calls["count"] += 1
        return _log_result(logql, "payment failed")

    monkeypatch.setattr(LokiService, "_query_range_uncached", fake_query)
    monkeypatch.setattr(loki_module, "get_cache", lambda: fake)
    service = LokiService(base_url="http://loki.invalid")
    now = datetime.now(UTC)

    await service.query_range(
        '{service="payment-api"}', now - timedelta(seconds=60), now, use_cache=True
    )
    await service.query_range('{service="payment-api"}', now - timedelta(seconds=60), now)

    assert calls["count"] == 2
