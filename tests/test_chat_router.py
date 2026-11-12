from datetime import UTC, datetime

import pytest

from app.agents.router import greeting_reply, route_message
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


@pytest.mark.parametrize(
    ("text", "key"), [("Hii", "hi"), ("hello", "hello"), ("Thank you!", "thank you")]
)
def test_greetings_are_canned(text: str, key: str) -> None:
    assert greeting_reply(text) is not None


def test_greeting_is_not_matched_inside_an_incident_message() -> None:
    assert greeting_reply("hi, payment-api returns 500") is None


async def test_route_message_answers_greeting_without_the_agent() -> None:
    routed = await route_message("Hii")
    assert routed.reply is not None
    assert routed.text == "Hii"


async def test_route_message_passes_investigations_to_the_agent() -> None:
    routed = await route_message("Investigate payment-api HTTP 500 errors")
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


async def test_yes_is_never_an_approval_in_chat() -> None:
    # A bare "yes" goes to the agent, which has no approve tool, so chat cannot approve anything.
    routed = await route_message("Yes")
    assert routed.reply is None


def test_no_chat_tool_can_approve_or_reject() -> None:
    from app.tools.chat_tools import TOOLS

    names = {tool.name for tool in TOOLS}
    assert not any(word in name for name in names for word in ("approve", "reject", "execute"))


async def test_dependency_question_is_answered_from_the_map() -> None:
    routed = await route_message("What services depend on order-service?")
    assert routed.reply is not None
    assert "api-gateway" in routed.reply and "mobile-app" in routed.reply


async def test_dependency_question_for_payment_api_lists_downstream() -> None:
    routed = await route_message(
        "Examine service dependencies for payment-api. Identify upstream and downstream."
    )
    assert routed.reply is not None
    assert "postgres" in routed.reply and "order-service" in routed.reply


async def test_dependency_question_without_known_service_goes_to_agent() -> None:
    routed = await route_message("What depends on the billing system?")
    assert routed.reply is None


def test_missing_signal_is_unknown_not_zero() -> None:
    missing_cpu = GoldenSignalMetrics(
        service="payment-api",
        error_rate_5xx_percent=0.0,
        request_rate_per_sec=8.0,
        p95_latency_ms=35.0,
        cpu_usage_percent=0.0,
        memory_usage_percent=0.0,
        missing_signals=["cpu_usage_percent"],
        collected_at=datetime.now(UTC),
    )
    table = golden_table(missing_cpu)
    assert "| CPU usage | `n/a` | ⚪ not collected |" in table
    verdict = status_verdict("payment-api", missing_cpu, "1 min", HEALTHY)
    assert "CPU n/a" in verdict
    assert "CPU `0.0%`" not in verdict


def test_missing_request_metrics_are_not_reported_as_no_traffic() -> None:
    missing_rate = GoldenSignalMetrics(
        service="payment-api",
        error_rate_5xx_percent=0.0,
        request_rate_per_sec=0.0,
        p95_latency_ms=0.0,
        cpu_usage_percent=5.0,
        memory_usage_percent=0.0,
        missing_signals=["request_rate_per_sec", "error_rate_5xx_percent", "p95_latency_ms"],
        collected_at=datetime.now(UTC),
    )
    assert "not available" in status_verdict("payment-api", missing_rate, "1 min", HEALTHY)


def test_error_rate_from_too_few_requests_is_not_reported_as_a_fault() -> None:
    from datetime import UTC, datetime

    # 0.01 requests per second over 60 s is under one request: a 99% error rate here is noise.
    sparse = GoldenSignalMetrics(
        service="payment-api",
        error_rate_5xx_percent=99.0,
        request_rate_per_sec=0.01,
        p95_latency_ms=2300.0,
        cpu_usage_percent=7.0,
        memory_usage_percent=20.0,
        window_seconds=60,
        collected_at=datetime.now(UTC),
    )
    assert sparse.rates_measured is False

    text = status_verdict("payment-api", sparse, "1 min", HEALTHY)
    assert "5xx" not in text.split("·")[0]
    assert "unverified" in text
    assert "degraded" not in text


def test_rates_measured_with_enough_requests() -> None:
    from datetime import UTC, datetime

    busy = GoldenSignalMetrics(
        service="payment-api",
        error_rate_5xx_percent=0.5,
        request_rate_per_sec=2.0,
        p95_latency_ms=120.0,
        cpu_usage_percent=7.0,
        memory_usage_percent=20.0,
        window_seconds=60,
        collected_at=datetime.now(UTC),
    )
    assert busy.rates_measured is True
    assert busy.model_dump(mode="json")["rates_measured"] is True


@pytest.mark.parametrize(
    "text",
    [
        "Any incident matching CPU burn?",
        "What incidents involved CPU burn?",
        "Search past incidents for CPU saturation",
        "How many incidents had high CPU?",
    ],
)
def test_incident_history_questions_are_not_answered_with_live_metrics(text: str) -> None:
    from app.services.live_status import classify_live_request

    assert classify_live_request(text) is None


def test_live_cpu_question_still_gets_live_metrics() -> None:
    from app.services.live_status import classify_live_request

    request = classify_live_request("What is the CPU usage right now?")
    assert request is not None and request.kind == "metrics"


async def test_missing_signals_are_null_and_error_status_is_plain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import chat_tools

    no_traffic = GoldenSignalMetrics(
        service="payment-api",
        error_rate_5xx_percent=0.0,
        request_rate_per_sec=0.0,
        p95_latency_ms=0.0,
        cpu_usage_percent=0.3,
        memory_usage_percent=0.0,
        missing_signals=["error_rate_5xx_percent", "p95_latency_ms"],
        window_seconds=60,
        collected_at=datetime.now(UTC),
    )

    class _Prom:
        async def get_golden_signals(self, **kwargs):
            return no_traffic

    monkeypatch.setattr(chat_tools, "get_prometheus_service", lambda: _Prom())
    result = await chat_tools.get_live_golden_signals.ainvoke({"service": "payment-api"})

    assert result["error_rate_5xx_percent"] is None
    assert result["p95_latency_ms"] is None
    assert result["cpu_usage_percent"] == 0.3
    assert "rates_measured" not in result
    assert result["error_and_latency"].startswith("not measured")


async def test_start_investigation_refuses_a_search_for_past_incidents() -> None:
    from app.tools import chat_tools

    result = await chat_tools.start_investigation.ainvoke(
        {
            "service": "payment-api",
            "symptoms": "Search past incidents for database connection pool exhaustion",
        }
    )

    assert "error" in result
    assert "no investigation was opened" in result["error"]
