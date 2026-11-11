"""Severity from measured evidence. The wording of the symptoms is never used, so the same fault gets
the same severity however the question was phrased."""

from app.constants.enums import IncidentSeverity
from app.constants.thresholds import (
    CPU_CRITICAL_PCT,
    ERROR_RATE_CRITICAL_PCT,
    ERROR_RATE_FAULT_PCT,
    LATENCY_FAULT_MS,
)
from app.schemas.telemetry import GoldenSignalMetrics


def severity_from_evidence(signals: GoldenSignalMetrics | None) -> IncidentSeverity:
    """Severity from the golden signals. Error rate and latency count only when the window had enough
    requests to measure them; CPU is read directly and counts either way."""
    if signals is None:
        return IncidentSeverity.MEDIUM
    if signals.rates_measured:
        if signals.error_rate_5xx_percent >= ERROR_RATE_CRITICAL_PCT:
            return IncidentSeverity.CRITICAL
        if (
            signals.error_rate_5xx_percent >= ERROR_RATE_FAULT_PCT
            or signals.p95_latency_ms >= LATENCY_FAULT_MS
        ):
            return IncidentSeverity.HIGH
    if "cpu_usage_percent" not in signals.missing_signals and (
        signals.cpu_usage_percent >= CPU_CRITICAL_PCT
    ):
        return IncidentSeverity.HIGH
    return IncidentSeverity.MEDIUM
