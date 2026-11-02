from datetime import UTC, datetime

from pydantic import BaseModel, Field


class SeedHistoricalIncident(BaseModel):
    id: str
    service: str
    symptoms: str
    root_cause: str
    remediation: str
    outcome: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


DEFAULT_HISTORICAL_INCIDENTS: list[SeedHistoricalIncident] = [
    SeedHistoricalIncident(
        id="b1c2d3e4-f5a6-4b1c-9d2e-111111111111",
        service="payment-api",
        symptoms="payment-api returning HTTP 500 errors. Database connection timeout and connection pool exhausted.",
        root_cause="Connection leak introduced in v2.3.1 where unclosed session connections failed to return to the pool upon timeout, causing pool exhaustion.",
        remediation="ROLLBACK_DEPLOYMENT to previous release v2.3.0 and initiate rolling restart.",
        outcome="RESOLVED: Pool utilization dropped from 100% to 12%, HTTP 500 error rate returned to 0.0%.",
    ),
    SeedHistoricalIncident(
        id="b1c2d3e4-f5a6-4b1c-9d2e-222222222222",
        service="order-service",
        symptoms="Cascading 504 Gateway Timeout errors during checkout. Upstream worker pool saturated.",
        root_cause="Unbounded synchronous wait on downstream payment-api without active circuit breaking, cascading timeouts into order-service.",
        remediation="ENABLE_CIRCUIT_BREAKER and SCALE_UP_REPLICAS by +3.",
        outcome="RESOLVED: Fail-fast fallback engaged, p99 latency stabilized at 110ms.",
    ),
    SeedHistoricalIncident(
        id="b1c2d3e4-f5a6-4b1c-9d2e-333333333333",
        service="auth-service",
        symptoms="Container CrashLoopBackOff with Exit Code 137 (OOMKill) after sustained authentication traffic.",
        root_cause="Unbounded in-memory token blacklist cache grew without TTL or LRU eviction limits.",
        remediation="ADJUST_CACHE_POLICY to maxmemory-policy allkeys-lru and ROLLING_RESTART.",
        outcome="RESOLVED: Memory footprint stabilized under 512MB, zero crashes observed.",
    ),
    SeedHistoricalIncident(
        id="b1c2d3e4-f5a6-4b1c-9d2e-444444444444",
        service="postgres",
        symptoms="Active database queries locked for >60s, client connections timing out at gateway.",
        root_cause="Long-running analytic batch report holding exclusive lock on payments table during peak OLTP hours.",
        remediation="TERMINATE_DB_TRANSACTIONS on blocking backend PID and reschedule report to read-replica.",
        outcome="RESOLVED: Locks released immediately, client query wait times recovered to <15ms.",
    ),
]
