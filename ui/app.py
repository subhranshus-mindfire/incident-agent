"""Incident Investigation Console — Streamlit UI.

A ChatGPT-style dark chat interface for the autonomous incident investigation agent.
Streams replies, supports HITL approval, and chaos injection.
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
from collections.abc import Generator
from typing import Any
from urllib.parse import urlencode

from ui.helpers import api_request, ping_endpoint

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("incident_agent.ui")

AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")
PAYMENT_API_URL = os.getenv("PAYMENT_API_URL", "http://localhost:8080").rstrip("/")
ASSISTANT_AVATAR = "🤖"  # Streamlit only accepts standard emoji as avatars; other characters are read as file paths

# ---------------------------------------------------------------------------
# Page Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Incident Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

    :root { color-scheme: dark; }
    html, body, [class*="css"] { font-family: 'Inter', ui-sans-serif, system-ui, sans-serif !important; }
    code, pre { font-family: 'JetBrains Mono', ui-monospace, monospace !important; }

    /* ── App shell ── */
    .stApp { background: #212121 !important; color: #ECECEC; }
    header[data-testid="stHeader"] { background: transparent !important; }
    #MainMenu, footer, .stDeployButton, [data-testid="stDecoration"],
    [data-testid="stToolbar"], [data-testid="stToolbarActions"] { display: none !important; }
    .block-container {
        max-width: 768px !important;
        padding: 2.5rem 1rem 9rem 1rem !important;
        margin: 0 auto !important;
    }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] { background: #171717 !important; border-right: 1px solid #2A2A2A !important; }
    section[data-testid="stSidebar"] .stButton button {
        background: transparent !important;
        border: none !important;
        color: #ECECEC !important;
        text-align: left !important;
        justify-content: flex-start !important;
        border-radius: 8px !important;
        font-size: 0.85rem !important;
        font-weight: 400 !important;
        box-shadow: none !important;
        white-space: normal !important;
    }
    section[data-testid="stSidebar"] .stButton button:hover { background: #2A2A2A !important; }
    section[data-testid="stSidebar"] .stButton, section[data-testid="stSidebar"] .stButton > div { width: 100% !important; }
    section[data-testid="stSidebar"] .stButton button > div,
    section[data-testid="stSidebar"] .stButton button p { width: 100% !important; text-align: left !important; justify-content: flex-start !important; }
    .side-label { font-size: 0.72rem; color: #8E8EA0; margin: 18px 0 6px 4px; font-weight: 500; }
    .brand { font-weight: 600; color: #ECECEC; font-size: 0.95rem; padding: 4px 4px 12px 4px; }
    .svc-pill { display:flex; align-items:center; gap:8px; color:#8E8EA0; font-size:0.8rem; padding: 8px 4px; }
    .svc-dot { width:7px; height:7px; border-radius:50%; flex-shrink:0; }

    /* ── Welcome hero ── */
    .hero { text-align: center; padding: 2.5rem 0 1.5rem 0; }
    .hero-mark { font-size: 1.8rem; color: #10A37F; margin-bottom: 8px; }
    .hero h2 { font-size: 1.6rem !important; font-weight: 600 !important; color: #ECECEC !important; margin: 0 0 6px 0 !important; }
    .hero p { color: #8E8EA0; font-size: 0.95rem; margin: 0; }

    /* ── Chips and buttons in the main area ── */
    .block-container .stButton button {
        background: #2F2F2F !important;
        border: 1px solid #3A3A3A !important;
        color: #ECECEC !important;
        border-radius: 14px !important;
        text-align: left !important;
        white-space: normal !important;
        padding: 12px 14px !important;
        font-size: 0.85rem !important;
        line-height: 1.4 !important;
        box-shadow: none !important;
    }
    .block-container .stButton button:hover { background: #343434 !important; border-color: #4A4A4A !important; }
    .block-container [data-testid="stBaseButton-primary"] {
        background: #ECECEC !important;
        color: #171717 !important;
        border: none !important;
        font-weight: 600 !important;
        text-align: center !important;
    }
    .block-container [data-testid="stBaseButton-primary"] p { color: #171717 !important; }
    .block-container [data-testid="stBaseButton-primary"]:hover { background: #FFFFFF !important; }

    /* ── Chat messages ── */
    [data-testid="stChatMessage"] { background: transparent !important; padding: 0.6rem 0 !important; }
    .user-row { display: flex; justify-content: flex-end; margin: 0.6rem 0; }
    .user-bubble {
        background: #2F2F2F; color: #ECECEC; padding: 10px 16px; border-radius: 20px;
        max-width: 80%; white-space: pre-wrap; font-size: 0.95rem; line-height: 1.55;
    }

    /* ── Chat input ── */
    [data-testid="stChatInput"] {
        background: #2F2F2F !important;
        border: 1px solid #3A3A3A !important;
        border-radius: 24px !important;
    }
    [data-testid="stChatInput"] textarea { color: #ECECEC !important; background: transparent !important; }
    [data-testid="stChatInput"] button { background: #ECECEC !important; border-radius: 50% !important; }
    [data-testid="stChatInput"] button svg { fill: #171717 !important; color: #171717 !important; }
    [data-testid="stBottom"] > div { background: #212121 !important; }

    /* ── Markdown typography ── */
    .block-container h3 { font-size: 1.1rem !important; font-weight: 600 !important; color: #ECECEC !important; }
    .block-container h4 { font-size: 0.95rem !important; font-weight: 600 !important; color: #ECECEC !important; margin-top: 1.2rem !important; }
    .block-container p, .block-container li { color: #D1D5DB; line-height: 1.65; }
    code { color: #E5E7EB !important; background: #2F2F2F !important; border-radius: 6px !important; padding: 1px 6px !important; }
    pre { background: #171717 !important; border: 1px solid #2F2F2F !important; border-radius: 12px !important; }
    pre code { background: transparent !important; padding: 0 !important; }
    [data-testid="stMarkdownContainer"] div:has(> table) { border: none !important; box-shadow: none !important; }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin: 0.4rem 0; border: none !important; }
    th, td { border: none !important; background: transparent !important; }
    th { color: #8E8EA0 !important; font-weight: 500 !important; text-align: left; padding: 8px 10px !important; border-bottom: 1px solid #3A3A3A !important; }
    td { padding: 8px 10px !important; border-bottom: 1px solid #2A2A2A !important; color: #D1D5DB !important; }
    tr:last-child td { border-bottom: none !important; }

    /* ── Expanders and status ── */
    [data-testid="stExpander"] { background: #1B1B1B !important; border: 1px solid #2F2F2F !important; border-radius: 12px !important; }
    [data-testid="stStatus"] { background: #1B1B1B !important; border: 1px solid #2F2F2F !important; border-radius: 12px !important; }

    /* ── HITL approval card ── */
    .approval-card { background: #2A2A2A; border: 1px solid #4A3B1C; border-radius: 14px; padding: 16px 18px; margin: 12px 0 10px 0; }
    .approval-title { font-weight: 600; color: #F5D28A; font-size: 0.95rem; margin-bottom: 10px; }
    .approval-row { display: flex; gap: 12px; font-size: 0.88rem; color: #D1D5DB; padding: 4px 0; }
    .approval-row span:first-child { color: #8E8EA0; min-width: 84px; }

    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-thumb { background: #3A3A3A; border-radius: 6px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session State
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_incident" not in st.session_state:
    st.session_state.current_incident = None
if "preset_prompt" not in st.session_state:
    st.session_state.preset_prompt = None


# ---------------------------------------------------------------------------
# Streaming Helpers
# ---------------------------------------------------------------------------
def _stream_text(text: str, delay: float = 0.008) -> Generator[str, None, None]:
    """Yields the reply token by token, keeping its original whitespace and line breaks."""
    for token in re.findall(r"\S+\s*|\s+", text):
        yield token
        time.sleep(delay)


def _user_bubble(text: str) -> str:
    """Right-aligned user message, escaped so typed text can never inject markup."""
    return f'<div class="user-row"><div class="user-bubble">{html.escape(text)}</div></div>'


def _render_message(role: str, content: str) -> None:
    """Renders one stored chat message in the ChatGPT-style layout."""
    if role == "user":
        st.markdown(_user_bubble(content), unsafe_allow_html=True)
    else:
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            st.markdown(content)


def _is_stale_gate(code: int, resp: Any) -> bool:
    """True when the API says the investigation is no longer paused at the approval gate."""
    return code == 400 and isinstance(resp, dict) and resp.get("code") == "INVALID_STATE_TRANSITION"


def _close_stale_gate() -> None:
    """Drops an approval card whose investigation has already moved on, and explains why in chat."""
    st.session_state.current_incident = None
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": "This remediation is no longer waiting for approval. It was already decided, or the workflow has moved on.",
        }
    )
    st.rerun()


def _status_label(value: float, warn: float, crit: float, unit: str = "") -> str:
    if value >= crit:
        return f"🔴 {value:.1f}{unit}"
    if value >= warn:
        return f"🟡 {value:.1f}{unit}"
    return f"🟢 {value:.1f}{unit}"


# ---------------------------------------------------------------------------
# Intent Detection — Don't trigger the LangGraph agent for chit-chat
# ---------------------------------------------------------------------------
_INVESTIGATION_KEYWORDS = {
    "investigate",
    "check",
    "diagnose",
    "debug",
    "error",
    "fault",
    "issue",
    "incident",
    "500",
    "latency",
    "timeout",
    "crash",
    "payment",
    "api",
    "deployment",
    "deploy",
    "rollback",
    "metric",
    "log",
    "prometheus",
    "loki",
    "qdrant",
    "blast",
    "root cause",
    "rca",
    "remediat",
    "chaos",
    "deadlock",
    "connection pool",
    "cpu",
    "memory",
    "service",
    "health",
    "down",
    "slow",
    "failure",
    "alert",
    "outage",
}

_GREETING_RESPONSES: dict[str, str] = {
    "hi": "👋 Hey! I'm your incident investigation assistant. Tell me about a service issue or pick one of the suggested queries to get started.",
    "hello": "👋 Hello! I'm ready to investigate incidents. Describe a symptom or service name to begin.",
    "hey": '👋 Hey there! Describe an issue (e.g. *"payment-api is returning 500s"*) and I\'ll dig in.',
    "okay": "Got it! Ready when you are — just describe the incident you want me to investigate.",
    "ok": "Sure thing! What incident should I look into?",
    "thanks": "You're welcome! Let me know if you need another investigation.",
    "thank you": "Glad I could help! 🙌",
    "bye": "See you next time! Stay incident-free 🚀",
}

# Questions that only ask whether a service is up get a one-line answer.
_STATUS_PATTERN = re.compile(r"\b(down|up|status|healthy|alive|working|available|outage)\b")
_INVESTIGATE_WORDS = ("investigat", "diagnos", "debug", "analy")


def _squeeze(text: str) -> str:
    """Collapses repeated letters so 'hii' and 'helloo' match their canonical greetings."""
    return re.sub(r"(.)\1+", r"\1", text)


# Short replies that ask for action on whatever was discussed last, e.g. "fix it" after a status answer.
_FOLLOWUP_FIX_PATTERN = re.compile(
    r"^(?:please\s+)?(?:fix|remediate|resolve)"
    r"(?:\s+(?:it|this|that|those|these|them|the (?:faults?|issues?|problems?)))?[.!?]*$"
    r"|^(?:do it|go ahead)[.!?]*$",
    re.IGNORECASE,
)
_KNOWN_SERVICES = ("payment-api", "order-service", "auth-service")


def _resolve_followup(prompt: str, history: list[dict[str, Any]]) -> str:
    """Expands a short follow-up such as 'fix it' into a full request about the service last discussed."""
    if not _FOLLOWUP_FIX_PATTERN.match(prompt.strip()):
        return prompt
    last_reply = next((m["content"] for m in reversed(history) if m["role"] == "assistant"), "")
    service = next((s for s in _KNOWN_SERVICES if s in last_reply), "payment-api")
    return f"Investigate {service} degradation and propose a fix."


def _is_investigation_request(text: str) -> bool:
    """Returns True if the message is an investigation request vs. conversational."""
    low = text.lower().strip()
    # Very short messages are almost certainly not investigations
    if len(low) < 10:
        return False
    return any(kw in low for kw in _INVESTIGATION_KEYWORDS)


def _get_conversational_reply(text: str) -> str | None:
    """Returns a canned reply for common conversational messages, or None if unknown."""
    low = _squeeze(text.lower().strip().rstrip("!.,?"))
    for key, reply in _GREETING_RESPONSES.items():
        squeezed = _squeeze(key)
        if low == squeezed or low.startswith(squeezed + " "):
            return reply
    return None


# Words that narrow the answer to the sections the operator asked about.
# No match at all means a general investigation, so the full report is shown.
_FOCUS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "blast": ("blast", "depend", "upstream", "downstream", "topology"),
    "golden": ("golden", "signal", "latency", "cpu", "memory", "metric", "5xx", "error rate"),
    "deploy": ("deploy", "dep-", "release", "rollback", "regression", "version"),
    "history": ("past incident", "history", "historical", "similar", "previous", "seen before"),
    "logs": ("log", "loki", "stack trace"),
    "rca": ("root cause", "cause", "why", "rca", "remediat"),
}


def _detect_focus(prompt: str) -> frozenset[str]:
    """Returns the sections the prompt asks for; an empty set means the full report."""
    low = prompt.lower()
    focus = {key for key, words in _FOCUS_KEYWORDS.items() if any(w in low for w in words)}
    if _STATUS_PATTERN.search(low) and not any(w in low for w in _INVESTIGATE_WORDS):
        focus.add("status")
    return frozenset(focus)


def _golden_table(error_rate: float, p95_sec: float, cpu: float, request_rate: float) -> str:
    # Error rate and latency come from requests; with none in the window they are not measurements.
    traffic = request_rate > 0
    error_status = _status_label(error_rate, 3, 5, "%") if traffic else "⚪ no traffic"
    latency_status = _status_label(p95_sec * 1000, 500, 1000, "ms") if traffic else "⚪ no traffic"
    return (
        "#### Golden signals\n\n"
        "| Signal | Value | Status |\n"
        "|--------|-------|--------|\n"
        f"| 5xx error rate | `{error_rate:.2f}%` | {error_status} |\n"
        f"| p95 latency | `{p95_sec * 1000:.0f}ms` | {latency_status} |\n"
        f"| CPU usage | `{cpu:.1f}%` | {_status_label(cpu, 60, 80, '%')} |"
    )


def _verification_markdown(report: Any) -> str:
    """Renders the backend's post-remediation health report: measured before vs. after."""
    if not isinstance(report, dict):
        return "**Post-remediation verification:** no report was returned."
    verdict = "✅ Stabilized" if report.get("stabilized") else "⚠️ Not stabilized"
    return (
        f"**Post-remediation verification** — {verdict}\n\n"
        "| Signal | Before | After |\n"
        "|--------|--------|-------|\n"
        f"| 5xx error rate | `{float(report.get('previous_error_rate', 0.0)):.2f}%` "
        f"| `{float(report.get('current_error_rate', 0.0)):.2f}%` |\n"
        f"| p95 latency | `{float(report.get('previous_latency_ms', 0.0)):.0f}ms` "
        f"| `{float(report.get('current_latency_ms', 0.0)):.0f}ms` |\n\n"
        f"_{report.get('details', '')}_"
    )


# ---------------------------------------------------------------------------
# Live questions — time-scoped status, logs and metrics read telemetry directly.
# They never open an incident, so "is it up" always reflects the last few seconds.
# ---------------------------------------------------------------------------
_WINDOW_PATTERN = re.compile(r"\blast\s+(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m)\b")
_LIVE_DEFAULT_SECONDS = 60
_LIVE_MIN_SECONDS = 10  # payment-api is scraped every 5 s, so a 10 s rate still sees two samples


def _parse_window_seconds(low: str) -> int | None:
    """Reads phrases like 'last 10 seconds' or 'last 2 min' into seconds."""
    match = _WINDOW_PATTERN.search(low)
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    return amount * 60 if unit.startswith("m") else amount


def _window_label(seconds: int) -> str:
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min"


def _live_request(prompt: str) -> tuple[str, int] | None:
    """Detects a live status, log or metric question. Returns (kind, window_seconds) or None."""
    low = prompt.lower()
    if any(w in low for w in _INVESTIGATE_WORDS):
        return None
    window = max(_parse_window_seconds(low) or _LIVE_DEFAULT_SECONDS, _LIVE_MIN_SECONDS)
    focus = _detect_focus(prompt)
    if focus == frozenset({"status"}):
        return "status", window
    if re.search(r"\blogs?\b", low):
        return "logs", window
    if "golden" in focus and focus <= {"golden"}:
        return "metrics", window
    return None


def _fetch_live(path: str, params: dict[str, Any]) -> tuple[int, Any]:
    return api_request(
        "GET", f"{AGENT_API_URL}/api/v1/telemetry/{path}?{urlencode(params)}", timeout=10.0
    )


def _status_answer(
    service: str, sig: dict[str, Any], label: str, health: tuple[int, Any] | None
) -> str:
    """Combines the service's own health endpoint with recent traffic metrics.

    `health` is None for services without a health probe here.
    """
    error_rate = float(sig.get("error_rate_5xx_percent", 0.0))
    p95_ms = float(sig.get("p95_latency_ms", 0.0))
    cpu = float(sig.get("cpu_usage_percent", 0.0))
    rate = float(sig.get("request_rate_per_sec", 0.0))

    faults: list[str] = []
    if health is not None:
        code, body = health
        if code != 200 or not isinstance(body, dict):
            return f"🔴 **`{service}` is down.** Its health endpoint did not respond (HTTP {code})."
        if body.get("status") != "healthy":
            faults.append(f"health reports {body.get('status', 'unknown')}")
        faults += [
            f"active fault: {name}" for name, on in (body.get("active_chaos") or {}).items() if on
        ]

    if rate > 0:
        if error_rate >= 3.0:
            faults.append(f"5xx error rate {error_rate:.1f}%")
        if p95_ms >= 1000.0:
            faults.append(f"p95 latency {p95_ms:.0f}ms")
        traffic_line = (
            f"5xx `{error_rate:.2f}%` · p95 `{p95_ms:.0f}ms` · CPU `{cpu:.1f}%` · last {label}"
        )
    else:
        # Zero traffic makes the error rate 0 by arithmetic, so it proves nothing about health.
        traffic_line = f"No requests in the last {label}, so error rate and latency are unverified."

    if faults:
        return f"🔴 **`{service}` is degraded:** {'; '.join(faults)}. {traffic_line}"
    if health is None and rate <= 0:
        return f"⚪ **`{service}` status unknown.** No requests in the last {label}, so metrics can't confirm health."
    return f"🟢 **`{service}` is up.** Health endpoint responds; no fault detected. {traffic_line}"


def _live_answer(kind: str, window: int, service: str) -> str:
    label = _window_label(window)
    if kind in ("status", "metrics"):
        code, sig = _fetch_live(
            "metrics/golden-signals", {"service": service, "window_seconds": window}
        )
        if code != 200:
            return f"❌ Could not read live metrics for `{service}` (HTTP {code})."
        if kind == "status":
            health = (
                api_request("GET", f"{PAYMENT_API_URL}/health", timeout=3.0)
                if service == "payment-api"
                else None
            )
            return _status_answer(service, sig, label, health)
        return f"#### Golden signals · last {label}\n\n" + _golden_table(
            float(sig["error_rate_5xx_percent"]),
            float(sig["p95_latency_ms"]) / 1000,
            float(sig["cpu_usage_percent"]),
            float(sig["request_rate_per_sec"]),
        )

    code, result = _fetch_live(
        "logs/query",
        {
            "query": f'{{service="{service}"}}',
            "window_seconds": window,
            "limit": 200,
            "deduplicate": "false",
        },
    )
    if code != 200:
        return f"❌ Could not read logs for `{service}` (HTTP {code})."
    entries = [e for stream in result.get("streams", []) for e in stream.get("entries", [])]
    entries.sort(key=lambda e: str(e.get("timestamp", "")), reverse=True)
    if not entries:
        return f"No log lines from `{service}` in the last {label}."
    lines = [
        f"{str(e.get('timestamp', ''))[11:19]} {str(e.get('level', 'INFO')):<5} {e.get('line', '')}"
        for e in entries[:40]
    ]
    return (
        f"#### Logs · `{service}` · last {label}\n\n"
        f"{len(entries)} line(s), newest first, showing {min(len(entries), 40)}\n\n"
        f"```\n" + "\n".join(lines) + "\n```"
    )


# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="brand">✦ Incident Agent</div>', unsafe_allow_html=True)

    if st.button("＋  New chat", key="new_chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.current_incident = None
        st.rerun()

    st.markdown('<div class="side-label">Try asking</div>', unsafe_allow_html=True)
    suggested = [
        "Is payment-api up?",
        "Investigate payment-api HTTP 500 errors and connection pool timeouts",
        "Did deployment DEP-101 introduce a regression on payment-api?",
        "Check golden signals and blast radius for payment-api",
        "Search past incidents for database connection pool exhaustion",
    ]
    for idx, q in enumerate(suggested):
        if st.button(q, key=f"sq_{idx}", use_container_width=True):
            st.session_state.preset_prompt = q
            st.rerun()

    with st.expander("Chaos simulator"):
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔥 Deadlock", use_container_width=True):
                api_request("POST", f"{PAYMENT_API_URL}/chaos/db-deadlock")
                for i in range(8):
                    api_request(
                        "POST", f"{PAYMENT_API_URL}/pay", data={"amount": 25.0 + i}, timeout=2.0
                    )
                st.toast("DB deadlock injected — pool saturated", icon="⚠️")
        with c2:
            if st.button("💥 Bad deploy", use_container_width=True):
                api_request("POST", f"{PAYMENT_API_URL}/chaos/bad-deployment")
                for i in range(8):
                    api_request(
                        "POST", f"{PAYMENT_API_URL}/pay", data={"amount": 30.0 + i}, timeout=2.0
                    )
                st.toast("DEP-101 v2.3.1 regression active", icon="⚠️")
        if st.button("✅ Clear all chaos", use_container_width=True):
            api_request("POST", f"{PAYMENT_API_URL}/chaos/clear")
            st.toast("Service restored to healthy baseline.", icon="✅")

    pay_ok = ping_endpoint(f"{PAYMENT_API_URL}/health")
    dot_color = "#10A37F" if pay_ok else "#EF4444"
    svc_label = "payment-api · online" if pay_ok else "payment-api · offline"
    st.markdown(
        f'<div class="svc-pill"><span class="svc-dot" style="background:{dot_color};"></span>{svc_label}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# WELCOME — shown when there are no messages
# ---------------------------------------------------------------------------
if not st.session_state.messages:
    st.markdown(
        '<div class="hero"><div class="hero-mark">✦</div>'
        "<h2>What's happening with your services?</h2>"
        "<p>Describe a symptom, ask about a deployment, or check whether a service is up.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    g1, g2 = st.columns(2)
    g3, g4 = st.columns(2)

    with g1:
        if st.button(
            "Investigate HTTP 500 errors\nCheck logs, metrics and recent deploys on payment-api.",
            key="hero_g1",
            use_container_width=True,
        ):
            st.session_state.preset_prompt = "Investigate payment-api HTTP 500 errors. Check logs, metrics, and recent deployments."
            st.rerun()
    with g2:
        if st.button(
            "Deployment regression\nDid DEP-101 cause connection pool exhaustion on payment-api?",
            key="hero_g2",
            use_container_width=True,
        ):
            st.session_state.preset_prompt = "Investigate DEP-101 deployment regression on payment-api. Check error rates and Loki stack traces."
            st.rerun()
    with g3:
        if st.button(
            "Blast radius\nWhat does a payment-api failure affect upstream and downstream?",
            key="hero_g3",
            use_container_width=True,
        ):
            st.session_state.preset_prompt = "Examine service dependencies for payment-api. Identify upstream and downstream affected services."
            st.rerun()
    with g4:
        if st.button(
            "Past incidents\nSearch memory for connection pool timeouts and their fixes.",
            key="hero_g4",
            use_container_width=True,
        ):
            st.session_state.preset_prompt = "Search Qdrant vector memory for past incidents matching database connection pool timeout on payment-api."
            st.rerun()

# ---------------------------------------------------------------------------
# CHAT HISTORY
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    _render_message(msg["role"], msg["content"])

# ---------------------------------------------------------------------------
# HITL APPROVAL CARD
# ---------------------------------------------------------------------------
if st.session_state.current_incident:
    inc = st.session_state.current_incident
    p = inc.get("proposal", {})

    def _g(obj: Any, key: str, default: Any = "") -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    action = str(_g(p, "action_type", "ROLLBACK_DEPLOYMENT")).replace("RemediationActionType.", "")
    risk = str(_g(p, "risk_tier", "CRITICAL")).replace("RiskTier.", "")
    rationale = str(_g(p, "rationale", "Proposed to resolve detected root cause."))
    rollback = str(_g(p, "rollback_plan", "Revert to previous stable version."))

    st.markdown(
        '<div class="approval-card">'
        '<div class="approval-title">Approval needed before remediation</div>'
        f'<div class="approval-row"><span>Action</span><code>{action}</code></div>'
        f'<div class="approval-row"><span>Risk</span><span>{risk}</span></div>'
        f'<div class="approval-row"><span>Rationale</span><span>{rationale}</span></div>'
        f'<div class="approval-row"><span>Rollback</span><span>{rollback}</span></div>'
        "</div>",
        unsafe_allow_html=True,
    )

    hc1, hc2, hc3 = st.columns([1.5, 1, 1.3])
    with hc1:
        if st.button("Approve & execute", type="primary", use_container_width=True, key="hitl_app"):
            code, resp = api_request(
                "POST",
                f"{AGENT_API_URL}/api/v1/investigations/{inc['id']}/approve",
                data={"reason": "Approved by operator"},
            )
            if code == 200:
                state = resp.get("state", {})
                exec_res = state.get("execution_result", {})
                postmortem = state.get("postmortem") or {}
                # The API returns a PostmortemReport; show its Markdown, not the raw object
                postmortem_md = (
                    postmortem.get("markdown_content", "")
                    if isinstance(postmortem, dict)
                    else str(postmortem)
                )
                verify_md = _verification_markdown(state.get("verification_report"))
                ex_action = _g(exec_res, "action_type", action)
                ex_ok = bool(_g(exec_res, "success", False))
                ex_status = "SUCCESS" if ex_ok else "FAILED"
                ex_output = _g(exec_res, "message", "No execution result was returned.")
                content = (
                    f"### Remediation {'executed' if ex_ok else 'failed'}\n\n"
                    f"| Field | Value |\n|-------|-------|\n"
                    f"| Action | `{ex_action}` |\n"
                    f"| Status | `{ex_status}` |\n"
                    f"| Output | {ex_output} |\n\n"
                    f"{verify_md}\n\n"
                    f"Incident indexed into Qdrant vector memory.\n\n---\n\n{postmortem_md}"
                )
                st.session_state.messages.append({"role": "assistant", "content": content})
                st.session_state.current_incident = None
                st.rerun()
            elif _is_stale_gate(code, resp):
                _close_stale_gate()
            else:
                st.error(f"Approval failed: {resp}")

    with hc2:
        if st.button("Reject", use_container_width=True, key="hitl_rej"):
            code, resp = api_request(
                "POST",
                f"{AGENT_API_URL}/api/v1/investigations/{inc['id']}/reject",
                data={"reason": "Rejected by operator"},
            )
            if code == 200:
                content = (
                    "### Remediation rejected\n\n"
                    "Workflow finished safely — no production changes made."
                )
                st.session_state.messages.append({"role": "assistant", "content": content})
                st.session_state.current_incident = None
                st.rerun()
            elif _is_stale_gate(code, resp):
                _close_stale_gate()
            else:
                st.error(f"Rejection failed: {resp}")

    with hc3:
        if st.button("More diagnostics", use_container_width=True, key="hitl_diag"):
            code, _ = api_request(
                "POST",
                f"{AGENT_API_URL}/api/v1/investigations/{inc['id']}/diagnostics",
                data={"reason": "Additional diagnostics requested."},
            )
            if code == 200:
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": "Expanding diagnostics — routing into `node_expand_diagnostics` for deeper telemetry analysis.",
                    }
                )
                st.rerun()
            elif _is_stale_gate(code, _):
                _close_stale_gate()

# ---------------------------------------------------------------------------
# CHAT INPUT
# ---------------------------------------------------------------------------
user_prompt = st.chat_input("Ask about a service or describe an incident…")

if st.session_state.preset_prompt:
    user_prompt = st.session_state.preset_prompt
    st.session_state.preset_prompt = None

if user_prompt:
    prompt = user_prompt.strip()
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.markdown(_user_bubble(prompt), unsafe_allow_html=True)
    # Follow-ups like "fix it" are answered about the service discussed last
    prompt = _resolve_followup(prompt, st.session_state.messages[:-1])

    # ── Conversational intent: don't hit the API for chit-chat ──
    conv_reply = _get_conversational_reply(prompt)
    if conv_reply and not _is_investigation_request(prompt):
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            st.write_stream(_stream_text(conv_reply))
        st.session_state.messages.append({"role": "assistant", "content": conv_reply})
        st.stop()

    # ── Determine target service from prompt ──
    target_svc = "payment-api"
    lower = prompt.lower()
    if "order" in lower:
        target_svc = "order-service"
    elif "auth" in lower:
        target_svc = "auth-service"

    # ── Live, time-scoped questions read telemetry directly; no incident is opened ──
    live = _live_request(prompt)
    if live:
        kind, window = live
        answer = _live_answer(kind, window, target_svc)
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            st.write_stream(_stream_text(answer))
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.stop()

    # ── Everything else goes to the agent, which answers from live tools ──
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages[:-1]
        if m.get("role") in ("user", "assistant")
    ][-20:]
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        with st.spinner("Checking live telemetry…"):
            code, resp = api_request(
                "POST",
                f"{AGENT_API_URL}/api/v1/chat",
                data={"message": prompt, "history": history},
                timeout=180.0,
            )
        if code == 200:
            reply = str(resp.get("reply", ""))
        else:
            reply = f"❌ The agent request failed (HTTP {code}): {resp}"
        st.write_stream(_stream_text(reply))

    st.session_state.messages.append({"role": "assistant", "content": reply})

    # A new investigation waiting at the approval gate gets the approval card
    incident = resp.get("incident") if code == 200 else None
    if incident and incident.get("awaiting_approval") and incident.get("remediation_proposal"):
        st.session_state.current_incident = {
            "id": incident["incident_id"],
            "proposal": incident["remediation_proposal"],
            "service": "payment-api",
        }
        st.rerun()
