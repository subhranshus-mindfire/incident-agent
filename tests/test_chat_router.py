from datetime import UTC, datetime

import pytest

from app.agents.router import greeting_reply, resolve_follow_up, route_message
from app.schemas.telemetry import GoldenSignalMetrics
from app.services.live_status import (
    HealthProbe,
    LiveRequest,
    classify_live_request,
    golden_table,
    parse_window_seconds,
    resolve_service,
    status_verdict,
)


def signals(
    *, rate: float = 0.0, error_pct: float = 0.0, p95_ms: float = 0.0, cpu: float = 0.0
) -> GoldenSignalMetrics:
    return GoldenSignalMetrics(
        service="payment-api",
        error_rate_5xx_percent=error_pct,
        request_rate_per_sec=rate,
        p95_latency_ms=p95_ms,
        cpu_usage_percent=cpu,
        memory_usage_percent=0.0,
        collected_at=datetime.now(UTC),
    )


HEALTHY = HealthProbe(
    http_status=200, body={"status": "healthy", "active_chaos": {"deadlock": False}}
)


# --- window parsing -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("show logs of the last 10 seconds", 10),
        ("logs last 2 min", 120),
        ("last 5 s", 10),  # clamped to the minimum
        ("last 99 hours", None),  # not a supported unit
        ("is payment-api up", None),
    ],
)
def test_parse_window_seconds(text: str, expected: int | None) -> None:
    assert parse_window_seconds(text) == expected


# --- classification -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Is payment-api up?", LiveRequest("status", 60)),
        ("is the service down", LiveRequest("status", 60)),
        ("Show logs of the last 10 seconds for payment-api", LiveRequest("logs", 10)),
        ("Check golden signals for payment-api", LiveRequest("metrics", 60)),
        ("Investigate payment-api HTTP 500 errors", None),
        ("Did DEP-101 cause a regression?", None),
        ("Check golden signals and blast radius for payment-api", None),
        ("Who is the president?", None),
    ],
)
def test_classify_live_request(text: str, expected: LiveRequest | None) -> None:
    assert classify_live_request(text) == expected


def test_resolve_service_defaults_to_payment_api() -> None:
    assert resolve_service("is it up") == "payment-api"
    assert resolve_service("is order service up") == "order-service"
    assert resolve_service("auth status") == "auth-service"


# --- follow-ups and greetings ---------------------------------------------------------------


@pytest.mark.parametrize("text", ["Fix it", "fix", "Please fix this.", "Fix those", "do it"])
def test_follow_up_fix_is_rewritten_to_last_service(text: str) -> None:
    history = [{"role": "assistant", "content": "🔴 `payment-api` is degraded"}]
    assert (
        resolve_follow_up(text, history) == "Investigate payment-api degradation and propose a fix."
    )


def test_follow_up_with_named_service_is_untouched() -> None:
    assert resolve_follow_up("Fix the order-service", []) == "Fix the order-service"


@pytest.mark.parametrize(
    ("text", "key"), [("Hii", "hi"), ("hello", "hello"), ("Thank you!", "thank you")]
)
def test_greetings_are_canned(text: str, key: str) -> None:
    assert greeting_reply(text) is not None


def test_greeting_is_not_matched_inside_an_incident_message() -> None:
    assert greeting_reply("hi, payment-api returns 500") is None


async def test_route_message_answers_greeting_without_the_agent() -> None:
    routed = await route_message("Hii", [])
    assert routed.reply is not None
    assert routed.text == "Hii"


async def test_route_message_passes_investigations_to_the_agent() -> None:
    routed = await route_message("Investigate payment-api HTTP 500 errors", [])
    assert routed.reply is None


# --- status verdicts ------------------------------------------------------------------------


def test_status_healthy_without_traffic_says_error_rate_unverified() -> None:
    text = status_verdict("payment-api", signals(), "1 min", HEALTHY)
    assert text.startswith("🟢")
    assert "unverified" in text


def test_status_reports_down_when_health_endpoint_fails() -> None:
    text = status_verdict("payment-api", signals(), "1 min", HealthProbe(http_status=503, body={}))
    assert text.startswith("🔴") and "down" in text


def test_status_lists_active_faults_even_without_traffic() -> None:
    faulty = HealthProbe(
        http_status=200,
        body={"status": "degraded", "active_chaos": {"deadlock": True, "bad_deployment": False}},
    )
    text = status_verdict("payment-api", signals(), "1 min", faulty)
    assert "active fault: deadlock" in text
    assert "bad_deployment" not in text


def test_status_degraded_on_fault_level_error_rate() -> None:
    text = status_verdict(
        "payment-api", signals(rate=8, error_pct=98.9, p95_ms=2425), "1 min", HEALTHY
    )
    assert text.startswith("🔴")
    assert "5xx error rate 98.9%" in text


def test_status_unknown_for_service_without_health_probe_and_no_traffic() -> None:
    text = status_verdict("order-service", signals(), "1 min", None)
    assert text.startswith("⚪")


# --- golden table ---------------------------------------------------------------------------


def test_golden_table_marks_error_and_latency_as_no_traffic() -> None:
    table = golden_table(signals(cpu=12.0))
    assert table.count("⚪ no traffic") == 2
    assert "🟢 12.0%" in table


def test_golden_table_uses_shared_thresholds_with_traffic() -> None:
    table = golden_table(signals(rate=5, error_pct=4.0, p95_ms=600, cpu=10))
    assert "🟡 4.0%" in table  # between the fault (3%) and critical (5%) levels
    assert "🟡 600.0ms" in table  # between warn (500 ms) and fault (1000 ms)


async def test_yes_after_awaiting_approval_points_to_the_console() -> None:
    history = [
        {"role": "assistant", "content": "Status: 🔒 Awaiting human approval for remediation."}
    ]
    routed = await route_message("Yes", history)
    assert routed.reply is not None
    assert "Approve & execute" in routed.reply


async def test_yes_without_pending_approval_goes_to_the_agent() -> None:
    routed = await route_message("Yes", [{"role": "assistant", "content": "Hello there."}])
    assert routed.reply is None
