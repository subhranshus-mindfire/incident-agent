from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.chat_agent import _grounded_reply
from app.agents.grounding import causal_claims_without_traffic, reply_problems, unsupported_figures
from app.agents.severity import severity_from_evidence
from app.constants.enums import IncidentSeverity
from app.schemas.telemetry import GoldenSignalMetrics


def signals(
    *,
    rate: float = 0.0,
    error: float = 0.0,
    p95: float = 0.0,
    cpu: float = 0.0,
    window: float = 300,
) -> GoldenSignalMetrics:
    return GoldenSignalMetrics(
        service="payment-api",
        error_rate_5xx_percent=error,
        request_rate_per_sec=rate,
        p95_latency_ms=p95,
        cpu_usage_percent=cpu,
        memory_usage_percent=0.0,
        window_seconds=window,
        collected_at=datetime.now(UTC),
    )


# --- figures in replies are grounded in tool results -----------------------------------------


def test_figure_from_a_tool_result_is_grounded() -> None:
    assert unsupported_figures("CPU is 79.9%.", ['{"cpu_usage_percent": 79.9}']) == []


def test_rounded_figure_is_grounded() -> None:
    assert unsupported_figures("p95 is 2323ms.", ['{"p95_latency_ms": 2323.0}']) == []


def test_figure_no_tool_returned_is_flagged() -> None:
    assert unsupported_figures("CPU rose to 14%.", ['{"cpu_usage_percent": 79.9}']) == ["14%"]


def test_reply_without_figures_is_not_checked() -> None:
    assert unsupported_figures("The service is up.", []) == []


class _FakeLLM:
    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def ainvoke(self, messages: list) -> AIMessage:
        self.calls += 1
        return AIMessage(content=self._replies.pop(0))


async def test_fabricated_figure_is_rewritten_from_tool_results() -> None:
    messages = [ToolMessage(content='{"cpu_usage_percent": 79.9}', tool_call_id="1")]
    llm = _FakeLLM("CPU is 79.9%.")

    reply = await _grounded_reply(llm, messages, "CPU fell to 14% after the restart.")

    assert reply == "CPU is 79.9%."
    assert llm.calls == 1


async def test_figure_still_unsupported_after_rewrite_is_withheld() -> None:
    messages = [ToolMessage(content='{"cpu_usage_percent": 79.9}', tool_call_id="1")]
    llm = _FakeLLM("CPU is 14%.")

    reply = await _grounded_reply(llm, messages, "CPU fell to 14%.")

    assert "could not confirm" in reply
    assert "14%" not in reply


async def test_grounded_reply_is_returned_without_a_model_call() -> None:
    messages = [
        HumanMessage(content="cpu?"),
        ToolMessage(content='{"cpu": 79.9}', tool_call_id="1"),
    ]
    llm = _FakeLLM()

    assert await _grounded_reply(llm, messages, "CPU is 79.9%.") == "CPU is 79.9%."
    assert llm.calls == 0


# --- severity comes from measured evidence --------------------------------------------------


def test_no_signals_is_medium() -> None:
    assert severity_from_evidence(None) is IncidentSeverity.MEDIUM


def test_unmeasured_error_rate_does_not_raise_severity() -> None:
    # 0.01 requests per second over 300 s is 3 requests: the 99% is noise, not a fault.
    noisy = signals(rate=0.01, error=99.0, p95=2300.0)
    assert severity_from_evidence(noisy) is IncidentSeverity.MEDIUM


def test_measured_error_rate_sets_severity() -> None:
    assert severity_from_evidence(signals(rate=5.0, error=6.0)) is IncidentSeverity.CRITICAL
    assert severity_from_evidence(signals(rate=5.0, error=4.0)) is IncidentSeverity.HIGH


def test_measured_latency_sets_high() -> None:
    assert severity_from_evidence(signals(rate=5.0, p95=1500.0)) is IncidentSeverity.HIGH


def test_cpu_saturation_sets_high_even_without_traffic() -> None:
    assert severity_from_evidence(signals(cpu=85.0)) is IncidentSeverity.HIGH


def test_moderate_cpu_without_traffic_stays_medium() -> None:
    assert severity_from_evidence(signals(cpu=50.0)) is IncidentSeverity.MEDIUM


# --- causal claims need a measured error rate ------------------------------------------------


def test_causal_claim_is_flagged_when_traffic_was_not_measured() -> None:
    results = ['{"p99_latency_seconds": 2.4, "rates_measured": false}']
    assert causal_claims_without_traffic("High latency is likely causing the errors.", results) == [
        "causing"
    ]


def test_causal_claim_is_allowed_when_traffic_was_measured() -> None:
    results = ['{"p99_latency_seconds": 2.4, "rates_measured": true}']
    assert (
        causal_claims_without_traffic("High latency is likely causing the errors.", results) == []
    )


def test_reply_problems_reports_both_kinds_of_problem() -> None:
    results = ['{"rates_measured": false, "cpu": 2.7}']
    problems = reply_problems("Latency of 2400ms is causing the errors.", results)
    assert any("2400ms" in p for p in problems)
    assert any("causing" in p for p in problems)


def test_rca_ignores_latency_and_errors_without_traffic() -> None:
    from app.rca.engine import SREInvestigationEngine
    from app.schemas.agent_state import TelemetrySummary

    unmeasured = TelemetrySummary(
        p99_latency_seconds=2.4, http_error_rate_pct=99.0, cpu_usage_pct=2.7, rates_measured=False
    )
    hypotheses = SREInvestigationEngine().formulate_rca_hypotheses(
        service="payment-api",
        symptoms="HTTP 500 errors",
        telemetry=unmeasured,
        logs=[],
        runbooks=[],
    )
    titles = " ".join(h.title for h in hypotheses)
    assert "Upstream Dependency" not in titles
    assert "Compute Saturation" not in titles


def test_rca_uses_latency_when_traffic_was_measured() -> None:
    from app.rca.engine import SREInvestigationEngine
    from app.schemas.agent_state import TelemetrySummary

    measured = TelemetrySummary(
        p99_latency_seconds=2.4, http_error_rate_pct=6.0, cpu_usage_pct=10.0, rates_measured=True
    )
    hypotheses = SREInvestigationEngine().formulate_rca_hypotheses(
        service="payment-api",
        symptoms="HTTP 500 errors",
        telemetry=measured,
        logs=[],
        runbooks=[],
    )
    assert any("Upstream Dependency" in h.title for h in hypotheses)
