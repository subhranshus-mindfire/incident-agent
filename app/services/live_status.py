"""Live, time-scoped answers about a service: status, golden signals and logs.

These read telemetry directly, so they reflect the last few seconds and never open an incident.
The classification and rendering functions are pure, so they can be tested without a network.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx

from app.constants.live import (
    DEFAULT_WINDOW_SECONDS,
    GOLDEN_WORDS,
    INVESTIGATE_WORDS,
    LOGS_PATTERN,
    MAX_LOG_LINES,
    MAX_WINDOW_SECONDS,
    MIN_WINDOW_SECONDS,
    OTHER_TOPIC_WORDS,
    STATUS_PATTERN,
    WINDOW_PATTERN,
)
from app.constants.services import PRIMARY_SERVICE
from app.constants.thresholds import (
    CPU_CRITICAL_PCT,
    CPU_WARN_PCT,
    ERROR_RATE_CRITICAL_PCT,
    ERROR_RATE_FAULT_PCT,
    LATENCY_FAULT_MS,
    LATENCY_WARN_MS,
)
from app.schemas.telemetry import GoldenSignalMetrics, LogEntry
from app.services.clients import get_loki_service, get_prometheus_service
from app.services.loki_service import service_selector
from app.utils.formatting import status_label
from app.utils.time import window_label

logger = logging.getLogger("incident_agent.services.live_status")

LiveKind = Literal["status", "metrics", "logs"]


@dataclass(frozen=True)
class LiveRequest:
    kind: LiveKind
    window_seconds: int


@dataclass(frozen=True)
class HealthProbe:
    """Result of calling a service's own /health endpoint. `body` is empty when the call failed."""

    http_status: int
    body: dict[str, object]


def parse_window_seconds(text: str) -> int | None:
    """Reads phrases like 'last 10 seconds' or 'last 2 min' into seconds."""
    match = WINDOW_PATTERN.search(text.lower())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    seconds = amount * 60 if unit.startswith("m") else amount
    return max(MIN_WINDOW_SECONDS, min(seconds, MAX_WINDOW_SECONDS))


def resolve_service(text: str) -> str:
    """Picks the service a question is about. payment-api is the default."""
    low = text.lower()
    if "order" in low:
        return "order-service"
    if "auth" in low:
        return "auth-service"
    return PRIMARY_SERVICE


def classify_live_request(text: str) -> LiveRequest | None:
    """Returns a live request for status, log or metric questions, or None when the agent should answer."""
    low = text.lower()
    if any(word in low for word in INVESTIGATE_WORDS):
        return None
    if any(word in low for word in OTHER_TOPIC_WORDS):
        return None
    window = parse_window_seconds(text) or DEFAULT_WINDOW_SECONDS
    if LOGS_PATTERN.search(low):
        return LiveRequest("logs", window)
    golden = any(word in low for word in GOLDEN_WORDS)
    if STATUS_PATTERN.search(low) and not golden:
        return LiveRequest("status", window)
    if golden:
        return LiveRequest("metrics", window)
    return None


def golden_table(signals: GoldenSignalMetrics) -> str:
    """Golden-signal table. Missing data is shown as unknown; with no requests, error and latency are not measurements."""
    missing = set(signals.missing_signals)
    traffic = signals.request_rate_per_sec > 0 and "request_rate_per_sec" not in missing

    def cell(value: str, signal: str) -> str:
        return "n/a" if signal in missing else value

    if "error_rate_5xx_percent" in missing:
        error_status = "⚪ not collected"
    elif not traffic:
        error_status = "⚪ no traffic"
    else:
        error_status = status_label(
            signals.error_rate_5xx_percent, ERROR_RATE_FAULT_PCT, ERROR_RATE_CRITICAL_PCT, "%"
        )
    if "p95_latency_ms" in missing:
        latency_status = "⚪ not collected"
    elif not traffic:
        latency_status = "⚪ no traffic"
    else:
        latency_status = status_label(
            signals.p95_latency_ms, LATENCY_WARN_MS, LATENCY_FAULT_MS, "ms"
        )
    cpu_status = (
        "⚪ not collected"
        if "cpu_usage_percent" in missing
        else status_label(signals.cpu_usage_percent, CPU_WARN_PCT, CPU_CRITICAL_PCT, "%")
    )
    return (
        "| Signal | Value | Status |\n"
        "|--------|-------|--------|\n"
        f"| 5xx error rate | `{cell(f'{signals.error_rate_5xx_percent:.2f}%', 'error_rate_5xx_percent')}` | {error_status} |\n"
        f"| p95 latency | `{cell(f'{signals.p95_latency_ms:.0f}ms', 'p95_latency_ms')}` | {latency_status} |\n"
        f"| CPU usage | `{cell(f'{signals.cpu_usage_percent:.1f}%', 'cpu_usage_percent')}` | {cpu_status} |"
    )


def status_verdict(
    service: str,
    signals: GoldenSignalMetrics,
    label: str,
    health: HealthProbe | None,
) -> str:
    """One-line verdict from the service's health endpoint and recent traffic.

    `health` is None for services without a health probe.
    """
    missing = set(signals.missing_signals)
    faults: list[str] = []
    if health is not None:
        if health.http_status != 200:
            return f"🔴 **`{service}` is down.** Its health endpoint did not respond (HTTP {health.http_status})."
        if health.body.get("status") != "healthy":
            faults.append(f"health reports {health.body.get('status', 'unknown')}")
        active = health.body.get("active_chaos")
        if isinstance(active, dict):
            faults += [f"active fault: {name}" for name, on in active.items() if on]

    traffic_known = signals.rates_measured
    measured = traffic_known and not {"error_rate_5xx_percent", "p95_latency_ms"} & missing
    if measured:
        if signals.error_rate_5xx_percent >= ERROR_RATE_FAULT_PCT:
            faults.append(f"5xx error rate {signals.error_rate_5xx_percent:.1f}%")
        if signals.p95_latency_ms >= LATENCY_FAULT_MS:
            faults.append(f"p95 latency {signals.p95_latency_ms:.0f}ms")
    cpu_text = (
        "CPU n/a" if "cpu_usage_percent" in missing else f"CPU `{signals.cpu_usage_percent:.1f}%`"
    )
    if "request_rate_per_sec" in missing:
        traffic_line = f"Request metrics are not available, so error rate and latency are unverified. {cpu_text}."
    elif not traffic_known:
        # Too few requests make the error rate a fraction of one request, so it proves nothing about health.
        requests = signals.request_rate_per_sec * (signals.window_seconds or 0)
        traffic_line = (
            f"Only {requests:.0f} request(s) in the last {label}, so error rate and latency are unverified. "
            f"{cpu_text}."
        )
    else:
        traffic_line = (
            f"5xx `{signals.error_rate_5xx_percent:.2f}%` · p95 `{signals.p95_latency_ms:.0f}ms` · "
            f"{cpu_text} · last {label}"
        )

    if faults:
        return f"🔴 **`{service}` is degraded:** {'; '.join(faults)}. {traffic_line}"
    if health is None and not measured:
        return (
            f"⚪ **`{service}` status unknown.** No measured traffic in the last {label}, "
            "so metrics can't confirm health."
        )
    return f"🟢 **`{service}` is up.** Health endpoint responds; no fault detected. {traffic_line}"


def log_answer(service: str, label: str, entries: list[LogEntry]) -> str:
    if not entries:
        return f"No log lines from `{service}` in the last {label}."
    shown = entries[:MAX_LOG_LINES]
    lines = [f"{e.timestamp:%H:%M:%S} {e.level:<5} {e.line}" for e in shown]
    return (
        f"#### Logs · `{service}` · last {label}\n\n"
        f"{len(entries)} line(s), newest first, showing {len(shown)}\n\n"
        "```\n" + "\n".join(lines) + "\n```"
    )


async def fetch_health(service: str) -> HealthProbe | None:
    """Calls the service's /health endpoint. Returns None for services without one."""
    if service != PRIMARY_SERVICE:
        return None
    base_url = os.getenv("PAYMENT_API_URL", "http://payment-api:8080")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{base_url}/health")
    except httpx.HTTPError as exc:
        logger.warning(f"Health probe for {service} failed: {exc}")
        return HealthProbe(http_status=503, body={})
    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    return HealthProbe(http_status=res.status_code, body=body if isinstance(body, dict) else {})


async def answer_live(request: LiveRequest, service: str) -> str:
    """Runs a live request against Prometheus, Loki and the service's health endpoint."""
    label = window_label(request.window_seconds)
    if request.kind == "logs":
        now = datetime.now(UTC)
        try:
            result = await get_loki_service().query_range(
                use_cache=True,
                logql=service_selector(service),
                start=now - timedelta(seconds=request.window_seconds),
                end=now,
                limit=200,
                deduplicate=False,
            )
        except Exception as exc:
            logger.warning(f"Live log query failed: {exc}")
            return f"❌ Could not read logs for `{service}`: {exc}"
        entries = sorted(
            (entry for stream in result.streams for entry in stream.entries),
            key=lambda entry: entry.timestamp,
            reverse=True,
        )
        return log_answer(service, label, entries)

    try:
        signals = await get_prometheus_service().get_golden_signals(
            use_cache=True, service=service, window_seconds=request.window_seconds
        )
    except Exception as exc:
        logger.warning(f"Live metrics query failed: {exc}")
        return f"❌ Could not read live metrics for `{service}`: {exc}"

    if request.kind == "metrics":
        return f"#### Golden signals · last {label}\n\n" + golden_table(signals)

    health = await fetch_health(service)
    return status_verdict(service, signals, label, health)
