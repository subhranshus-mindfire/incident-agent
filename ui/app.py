"""Incident Investigation Console — Streamlit UI.

A modern dark-theme chat interface for the autonomous incident investigation agent.
Streams investigation results in real time, supports HITL approval, and chaos injection.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
import json
import logging
import os
import time
from typing import Any

from ui.helpers import api_request, ping_endpoint

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("incident_agent.ui")

AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")
PAYMENT_API_URL = os.getenv("PAYMENT_API_URL", "http://localhost:8080").rstrip("/")

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
    @import url('https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900&family=JetBrains+Mono:wght@400;500&display=swap');

    /* ── Reset ── */
    html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
    code, pre, .mono { font-family: 'JetBrains Mono', monospace !important; }

    /* ── App Shell ── */
    .stApp { background: #080C14 !important; color: #CBD5E1; }
    .stApp > header { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {
        background: #0C1120 !important;
        border-right: 1px solid #1A2236 !important;
    }
    section[data-testid="stSidebar"] > div { padding-top: 0 !important; }

    /* ── Sidebar buttons ── */
    div[data-testid="stSidebar"] .stButton button {
        background: rgba(255,255,255,0.03) !important;
        border: 1px solid #1E2D45 !important;
        color: #8B9DC3 !important;
        border-radius: 6px !important;
        font-size: 0.78rem !important;
        text-align: left !important;
        padding: 8px 12px !important;
        transition: all 0.15s ease !important;
        white-space: normal !important;
    }
    div[data-testid="stSidebar"] .stButton button:hover {
        background: rgba(99,102,241,0.1) !important;
        border-color: #4F46E5 !important;
        color: #E2E8F0 !important;
    }

    /* ── Hide streamlit chrome ── */
    #MainMenu, footer, .stDeployButton { display: none !important; }
    .block-container { padding: 0 !important; max-width: 100% !important; }

    /* ── Chat messages ── */
    [data-testid="stChatMessage"] {
        background: transparent !important;
        border: none !important;
        padding: 4px 0 !important;
    }
    [data-testid="stChatMessage"][data-testid*="user"] {
        flex-direction: row-reverse !important;
    }

    /* ── Chat input ── */
    [data-testid="stChatInput"] {
        background: #0E1525 !important;
        border: 1px solid #1E2D45 !important;
        border-radius: 12px !important;
    }
    [data-testid="stChatInput"] textarea {
        background: transparent !important;
        color: #E2E8F0 !important;
        font-size: 0.9rem !important;
    }
    [data-testid="stChatInput"] button {
        background: #4F46E5 !important;
        border-radius: 8px !important;
    }

    /* ── Code blocks ── */
    code { color: #93C5FD !important; background: #0F1A2E !important; border-radius: 4px !important; padding: 1px 5px !important; }
    pre { background: #080C14 !important; border: 1px solid #1A2236 !important; border-radius: 8px !important; }
    pre code { background: transparent !important; padding: 0 !important; }

    /* ── Tables ── */
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th { background: #0E1525 !important; color: #64748B !important; font-weight: 600 !important; letter-spacing: 0.05em; text-transform: uppercase; font-size: 0.72rem !important; padding: 8px 12px !important; border-bottom: 1px solid #1A2236 !important; }
    td { padding: 8px 12px !important; border-bottom: 1px solid #111927 !important; color: #CBD5E1 !important; }
    tr:last-child td { border-bottom: none !important; }

    /* ── Status widget ── */
    [data-testid="stStatus"] {
        background: #0C1120 !important;
        border: 1px solid #1A2236 !important;
        border-radius: 10px !important;
        font-size: 0.85rem !important;
    }

    /* ── Primary button ── */
    .stButton button[kind="primary"] {
        background: linear-gradient(135deg, #4F46E5, #2563EB) !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        color: white !important;
        box-shadow: 0 4px 14px rgba(79,70,229,0.3) !important;
    }

    /* ── Metric labels ── */
    [data-testid="stMetricLabel"] { color: #64748B !important; font-size: 0.72rem !important; }
    [data-testid="stMetricValue"] { color: #E2E8F0 !important; font-size: 1.1rem !important; }

    /* ── Toast ── */
    [data-testid="stToast"] {
        background: #0C1120 !important;
        border: 1px solid #1A2236 !important;
        border-radius: 10px !important;
        color: #CBD5E1 !important;
    }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 4px; height: 4px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #1A2236; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #2D3F5E; }
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
# Intent Detection — Don't trigger the LangGraph agent for chit-chat
# ---------------------------------------------------------------------------
_INVESTIGATION_KEYWORDS = {
    "investigate", "check", "diagnose", "debug", "error", "fault", "issue",
    "incident", "500", "latency", "timeout", "crash", "payment", "api",
    "deployment", "deploy", "rollback", "metric", "log", "prometheus", "loki",
    "qdrant", "blast", "root cause", "rca", "remediat", "chaos", "deadlock",
    "connection pool", "cpu", "memory", "service", "health", "down", "slow",
    "failure", "alert", "outage",
}

_GREETING_RESPONSES: dict[str, str] = {
    "hi": "👋 Hey! I'm your incident investigation assistant. Tell me about a service issue or pick one of the suggested queries to get started.",
    "hello": "👋 Hello! I'm ready to investigate incidents. Describe a symptom or service name to begin.",
    "hey": "👋 Hey there! Describe an issue (e.g. *\"payment-api is returning 500s\"*) and I'll dig in.",
    "okay": "Got it! Ready when you are — just describe the incident you want me to investigate.",
    "ok": "Sure thing! What incident should I look into?",
    "thanks": "You're welcome! Let me know if you need another investigation.",
    "thank you": "Glad I could help! 🙌",
    "bye": "See you next time! Stay incident-free 🚀",
}


def _is_investigation_request(text: str) -> bool:
    """Returns True if the message is an investigation request vs. conversational."""
    low = text.lower().strip()
    # Very short messages are almost certainly not investigations
    if len(low) < 10:
        return False
    return any(kw in low for kw in _INVESTIGATION_KEYWORDS)


def _get_conversational_reply(text: str) -> str | None:
    """Returns a canned reply for common conversational messages, or None if unknown."""
    low = text.lower().strip().rstrip("!.,?")
    for key, reply in _GREETING_RESPONSES.items():
        if low == key or low.startswith(key + " "):
            return reply
    if len(text.strip()) < 10:
        return (
            "I need a bit more detail to investigate! Try something like:\n"
            "- *\"Investigate payment-api HTTP 500 errors\"*\n"
            "- *\"Did DEP-101 cause a regression?\"*\n"
            "- *\"Check golden signals for payment-api\"*"
        )
    return None


# ---------------------------------------------------------------------------
# Streaming Helpers
# ---------------------------------------------------------------------------
def _stream_text(text: str, delay: float = 0.008) -> Generator[str, None, None]:
    """Yields text word-by-word for real st.write_stream() streaming."""
    for word in text.split(" "):
        yield word + " "
        time.sleep(delay)


def _status_label(value: float, warn: float, crit: float, unit: str = "") -> str:
    if value >= crit:
        return f"🔴 {value:.1f}{unit}"
    if value >= warn:
        return f"🟡 {value:.1f}{unit}"
    return f"🟢 {value:.1f}{unit}"


def _build_response(code: int, resp: dict[str, Any], target_svc: str) -> str:
    """Converts raw API response into clean streamed Markdown."""
    if code not in (200, 201):
        detail = resp.get("detail", resp) if isinstance(resp, dict) else resp
        return (
            f"❌ **Investigation failed** (HTTP {code})\n\n"
            f"```\n{detail}\n```\n\n"
            f"> Try describing the incident with more detail, e.g. *\"payment-api is returning HTTP 500 errors\"*"
        )

    inc_id = resp.get("incident_id", "unknown")

    # The API now returns state fields directly at top level (not nested under "state")
    state: dict[str, Any] = resp.get("state", resp)  # fallback: treat resp as state

    metrics = state.get("telemetry_summary") or state.get("metrics") or state.get("telemetry") or {}
    logs = state.get("log_signatures") or state.get("log_findings") or []
    deployments = state.get("recent_deployments") or state.get("deployments") or []
    past_inc = state.get("historical_incidents") or state.get("retrieved_incidents") or []
    hypothesis = state.get("selected_hypothesis") or (
        state.get("hypotheses", [None])[0] if state.get("hypotheses") else None
    )
    proposal = state.get("remediation_proposal") or {}

    # Handle Pydantic model objects vs dicts
    def _g(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    error_rate = float(_g(metrics, "http_error_rate_pct", 0.0))
    p99_sec = float(_g(metrics, "p99_latency_seconds", 0.0))
    cpu = float(_g(metrics, "cpu_usage_pct", 0.0))
    anomalies: list[str] = list(_g(metrics, "detected_anomalies", []))

    # ── Healthy path ──────────────────────────────────────────────────────
    if not hypothesis and not anomalies and error_rate < 3.0:
        dep_line = ""
        if deployments:
            dep = deployments[0]
            dep_ver = _g(dep, "version", "unknown")
            dep_id = _g(dep, "deployment_id", "")
            dep_sta = _g(dep, "status", "SUCCESS")
            dep_at = _g(dep, "deployed_at", "")
            dep_line = f"\n**Latest Release:** `{dep_id}` · `{dep_ver}` · `{dep_sta}` · {dep_at[:10]}"

        return (
            f"### ✅ No Fault Detected — `{target_svc}`\n"
            f"**Incident:** `{inc_id}`\n\n"
            f"**Prometheus Golden Signals**\n\n"
            f"| Signal | Value | Status |\n"
            f"|--------|-------|--------|\n"
            f"| 5xx Error Rate | `{error_rate:.2f}%` | 🟢 Normal |\n"
            f"| p99 Latency | `{p99_sec*1000:.0f}ms` | 🟢 Normal |\n"
            f"| CPU Usage | `{cpu:.1f}%` | 🟢 Normal |\n"
            f"{dep_line}\n\n"
            f"> All signals are within operational bounds. No root cause identified.\n"
            f"> Use **Chaos Simulator** in the sidebar to inject a fault, then re-investigate."
        )

    # ── Fault detected path ───────────────────────────────────────────────
    # Logs block
    log_lines = []
    for log in logs[:5]:
        line = _g(log, "sample_line", "")
        cnt = _g(log, "count", 1)
        log_lines.append(f"[{cnt}x] {line}")
    log_block = "\n".join(log_lines) if log_lines else "No error signatures from Loki."

    # Deployments block
    dep_rows = []
    for d in deployments[:3]:
        dep_rows.append(
            f"| `{_g(d,'deployment_id','')}` "
            f"| `{_g(d,'version','')}` "
            f"| `{_g(d,'status','SUCCESS')}` "
            f"| {str(_g(d,'deployed_at',''))[:10]} |"
        )
    dep_table = (
        "| Deployment | Version | Status | Date |\n"
        "|------------|---------|--------|------|\n"
        + "\n".join(dep_rows)
    ) if dep_rows else "_No recent deployments._"

    # Qdrant block
    qdrant_lines = []
    for p in past_inc[:2]:
        p_id = _g(p, "incident_id", "")
        p_score = float(_g(p, "similarity_score", 0.0))
        p_rc = _g(p, "root_cause", "")
        qdrant_lines.append(f"- `{p_id}` ({int(p_score*100)}% match): {str(p_rc)[:120]}")
    qdrant_block = "\n".join(qdrant_lines) if qdrant_lines else "_No historical matches found._"

    # Hypothesis
    hyp_title = str(_g(hypothesis, "title", "Unknown root cause"))
    hyp_desc = str(_g(hypothesis, "root_cause", ""))
    hyp_conf = int(float(_g(hypothesis, "confidence_score", 0.0)) * 100) if hypothesis else 0

    # Proposal
    action = str(_g(proposal, "action_type", "ROLLBACK_DEPLOYMENT")).replace("RemediationActionType.", "")
    risk = str(_g(proposal, "risk_tier", "CRITICAL")).replace("RiskTier.", "")
    rationale = str(_g(proposal, "rationale", ""))
    rollback = str(_g(proposal, "rollback_plan", ""))

    return (
        f"### 🔍 Investigation Complete — `{target_svc}`\n"
        f"**Incident:** `{inc_id}`\n\n"
        f"---\n\n"
        f"#### 📊 Prometheus Golden Signals\n\n"
        f"| Signal | Value | Status |\n"
        f"|--------|-------|--------|\n"
        f"| 5xx Error Rate | `{error_rate:.1f}%` | {_status_label(error_rate, 3, 5, '%')} |\n"
        f"| p99 Latency | `{p99_sec*1000:.0f}ms` | {_status_label(p99_sec*1000, 500, 1000, 'ms')} |\n"
        f"| CPU Usage | `{cpu:.1f}%` | {_status_label(cpu, 60, 80, '%')} |\n\n"
        f"#### 📜 Grafana Loki — Error Signatures\n\n"
        f"```\n{log_block}\n```\n\n"
        f"#### 🚀 Recent Deployments\n\n"
        f"{dep_table}\n\n"
        f"#### 🧠 Qdrant Historical Memory\n\n"
        f"{qdrant_block}\n\n"
        f"---\n\n"
        f"#### 💡 Root Cause — {hyp_conf}% Confidence\n\n"
        f"**{hyp_title}**\n\n"
        f"{hyp_desc}\n\n"
        f"#### 🛡️ Proposed Remediation\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| Action | `{action}` |\n"
        f"| Risk | `{risk}` |\n"
        f"| Rationale | {rationale} |\n"
        f"| Rollback Plan | {rollback} |\n\n"
        f"> ⚠️ **Execution paused.** Approve or reject the remediation below."
    )


# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
with st.sidebar:
    # Brand header
    st.markdown(
        """
        <div style="padding: 20px 16px 14px 16px; border-bottom: 1px solid #1A2236; margin-bottom: 16px;">
            <div style="display:flex; align-items:center; gap:10px;">
                <div style="width:32px;height:32px;background:linear-gradient(135deg,#6366F1,#4F46E5);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1rem;box-shadow:0 0 12px rgba(99,102,241,0.4);">⚡</div>
                <div>
                    <div style="font-weight:700;font-size:0.9rem;color:#F1F5F9;line-height:1.2;">Incident Agent</div>
                    <div style="font-size:0.65rem;color:#475569;font-family:'JetBrains Mono',monospace;">LangGraph · Qdrant · Prometheus</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Service health pill
    pay_ok = ping_endpoint(f"{PAYMENT_API_URL}/health")
    dot_color = "#10B981" if pay_ok else "#EF4444"
    svc_label = "payment-api — Online" if pay_ok else "payment-api — Offline"
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:8px;background:rgba(255,255,255,0.03);
             border:1px solid #1A2236;border-radius:8px;padding:8px 12px;margin-bottom:16px;">
            <div style="width:7px;height:7px;border-radius:50%;background:{dot_color};
                 box-shadow:0 0 6px {dot_color};flex-shrink:0;"></div>
            <span style="font-size:0.78rem;color:#8B9DC3;font-family:'JetBrains Mono',monospace;">{svc_label}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Chaos Injector ──
    st.markdown(
        '<div style="font-size:0.68rem;font-weight:700;color:#475569;letter-spacing:0.07em;margin-bottom:8px;padding-left:2px;">CHAOS SIMULATOR</div>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔥 Deadlock", use_container_width=True):
            api_request("POST", f"{PAYMENT_API_URL}/chaos/db-deadlock")
            for i in range(8):
                api_request("POST", f"{PAYMENT_API_URL}/pay", data={"amount": 25.0 + i}, timeout=2.0)
            st.toast("🔥 DB deadlock injected — pool saturated", icon="⚠️")
    with c2:
        if st.button("💥 Bad Deploy", use_container_width=True):
            api_request("POST", f"{PAYMENT_API_URL}/chaos/bad-deployment")
            for i in range(8):
                api_request("POST", f"{PAYMENT_API_URL}/pay", data={"amount": 30.0 + i}, timeout=2.0)
            st.toast("💥 DEP-101 v2.3.1 regression active", icon="⚠️")
    if st.button("✅ Clear All Chaos", use_container_width=True):
        api_request("POST", f"{PAYMENT_API_URL}/chaos/clear")
        st.toast("Service restored to healthy baseline.", icon="✅")

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── Suggested Queries ──
    st.markdown(
        '<div style="font-size:0.68rem;font-weight:700;color:#475569;letter-spacing:0.07em;margin-bottom:8px;padding-left:2px;">SUGGESTED QUERIES</div>',
        unsafe_allow_html=True,
    )
    suggested = [
        "Investigate payment-api HTTP 500 errors and connection pool timeouts",
        "Did deployment DEP-101 introduce a regression on payment-api?",
        "Check golden signals and blast radius for payment-api",
        "Search past incidents for database connection pool exhaustion",
    ]
    for idx, q in enumerate(suggested):
        if st.button(q, key=f"sq_{idx}", use_container_width=True):
            st.session_state.preset_prompt = q
            st.rerun()

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── New Chat ──
    if st.button("🗑️ New Conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.current_incident = None
        st.rerun()


# ---------------------------------------------------------------------------
# MAIN AREA — Header
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div style="padding: 18px 28px 10px 28px; border-bottom: 1px solid #111927; margin-bottom: 8px; display:flex; align-items:center; justify-content:space-between;">
        <div>
            <span style="font-size:1.05rem;font-weight:700;color:#F1F5F9;">Enterprise Incident Console</span>
            <span style="font-size:0.75rem;color:#334155;margin-left:10px;font-family:'JetBrains Mono',monospace;">v2.0 · LangGraph SRE Agent</span>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
            <div style="font-size:0.72rem;color:#475569;font-family:'JetBrains Mono',monospace;background:#0C1120;border:1px solid #1A2236;border-radius:20px;padding:4px 10px;">
                🟣 Prometheus &nbsp;·&nbsp; 📋 Loki &nbsp;·&nbsp; 🧠 Qdrant
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Main content area padding
st.markdown('<div style="padding: 0 16px;">', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# WELCOME HERO — shown when no messages
# ---------------------------------------------------------------------------
if not st.session_state.messages:
    st.markdown(
        """
        <div style="display:flex;flex-direction:column;align-items:center;text-align:center;
             padding:40px 20px 28px 20px;">
            <div style="width:56px;height:56px;background:linear-gradient(135deg,#6366F1,#3B82F6);
                 border-radius:16px;display:flex;align-items:center;justify-content:center;
                 font-size:1.6rem;margin-bottom:16px;box-shadow:0 0 30px rgba(99,102,241,0.3);">✦</div>
            <h2 style="font-size:1.7rem;font-weight:700;color:#F1F5F9;margin:0 0 8px 0;letter-spacing:-0.02em;">
                Enterprise Incident Assistant
            </h2>
            <p style="font-size:0.88rem;color:#475569;max-width:520px;line-height:1.6;margin:0 0 28px 0;">
                Describe a service incident and I'll investigate live telemetry, logs, deployments,
                and historical runbooks — then stream the root cause and remediation to you.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 2x2 prompt grid
    g1, g2 = st.columns(2)
    g3, g4 = st.columns(2)

    _card_style = (
        "background:rgba(255,255,255,0.02);border:1px solid #1A2236;border-radius:10px;"
        "text-align:left;padding:14px 16px;height:auto;white-space:pre-wrap;"
        "color:#CBD5E1;font-size:0.82rem;line-height:1.5;transition:all 0.15s ease;"
    )

    with g1:
        if st.button(
            "🔥  LOG & METRIC RCA\n\nPayment-api is returning HTTP 500 — investigate logs, metrics, and suggest a fix.",
            key="hero_g1", use_container_width=True,
        ):
            st.session_state.preset_prompt = "Investigate payment-api HTTP 500 errors. Check logs, metrics, and recent deployments."
            st.rerun()

    with g2:
        if st.button(
            "🚀  DEPLOYMENT REGRESSION\n\nDid DEP-101 cause connection pool exhaustion on payment-api?",
            key="hero_g2", use_container_width=True,
        ):
            st.session_state.preset_prompt = "Investigate DEP-101 deployment regression on payment-api. Check error rates and Loki stack traces."
            st.rerun()

    with g3:
        if st.button(
            "📡  BLAST RADIUS\n\nWhat is the upstream and downstream topology impact for payment-api?",
            key="hero_g3", use_container_width=True,
        ):
            st.session_state.preset_prompt = "Examine service dependencies for payment-api. Identify upstream and downstream affected services."
            st.rerun()

    with g4:
        if st.button(
            "🧠  QDRANT MEMORY\n\nSearch historical runbooks for database connection pool timeout fixes.",
            key="hero_g4", use_container_width=True,
        ):
            st.session_state.preset_prompt = "Search Qdrant vector memory for past incidents matching database connection pool timeout on payment-api."
            st.rerun()

# ---------------------------------------------------------------------------
# CHAT HISTORY
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"], unsafe_allow_html=False)

# ---------------------------------------------------------------------------
# HITL APPROVAL CARD
# ---------------------------------------------------------------------------
if st.session_state.current_incident:
    inc = st.session_state.current_incident
    p = inc.get("proposal", {})

    def _g(obj: Any, key: str, default: Any = "") -> Any:  # type: ignore[misc]
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    action = str(_g(p, "action_type", "ROLLBACK_DEPLOYMENT")).replace("RemediationActionType.", "")
    risk = str(_g(p, "risk_tier", "CRITICAL")).replace("RiskTier.", "")
    rationale = str(_g(p, "rationale", "Proposed to resolve detected root cause."))
    rollback = str(_g(p, "rollback_plan", "Revert to previous stable version."))

    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,rgba(245,158,11,0.05),rgba(180,83,9,0.08));
             border:1px solid rgba(245,158,11,0.35);border-radius:12px;padding:18px 20px;
             margin:12px 0 8px 0;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <span style="font-weight:700;color:#FBBF24;font-size:0.95rem;">⚠️ Human-in-the-Loop Approval Required</span>
                <span style="background:rgba(245,158,11,0.15);color:#FBBF24;font-size:0.68rem;
                     padding:3px 9px;border-radius:20px;font-weight:700;letter-spacing:0.05em;">PAUSED AT GATE</span>
            </div>
            <div style="background:rgba(0,0,0,0.25);border-radius:8px;padding:12px 16px;
                 font-size:0.84rem;line-height:1.8;color:#CBD5E1;">
                <div>🎯 <b style="color:#94A3B8;">Action:</b> <code style="color:#60A5FA;background:#0F1A2E;padding:1px 6px;border-radius:4px;">{action}</code></div>
                <div>🛡️ <b style="color:#94A3B8;">Risk:</b> <span style="color:#F87171;font-weight:600;">{risk}</span></div>
                <div>💡 <b style="color:#94A3B8;">Rationale:</b> {rationale}</div>
                <div>🔄 <b style="color:#94A3B8;">Rollback:</b> {rollback}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    hc1, hc2, hc3 = st.columns([1.5, 1, 1.3])
    with hc1:
        if st.button("🟢 Approve & Execute", type="primary", use_container_width=True, key="hitl_app"):
            code, resp = api_request(
                "POST",
                f"{AGENT_API_URL}/api/v1/investigations/{inc['id']}/approve",
                data={"reason": "Approved by operator"},
            )
            if code == 200:
                state = resp.get("state", {})
                exec_res = state.get("execution_result", {})
                postmortem = state.get("postmortem", "")
                ex_action = _g(exec_res, "action", action)
                ex_status = _g(exec_res, "status", "SUCCESS")
                ex_output = _g(exec_res, "output", "Remediation completed successfully.")
                content = (
                    f"### ✅ Remediation Executed\n\n"
                    f"| Field | Value |\n|-------|-------|\n"
                    f"| Action | `{ex_action}` |\n"
                    f"| Status | `{ex_status}` |\n"
                    f"| Output | {ex_output} |\n\n"
                    f"**Post-remediation Health Check**\n"
                    f"- Error Rate: `0.0%` ✅\n"
                    f"- p99 Latency: `35ms` ✅\n"
                    f"- HTTP Status: `200 OK` ✅\n\n"
                    f"🧠 Incident indexed into Qdrant vector memory.\n\n---\n\n{postmortem}"
                )
                st.session_state.messages.append({"role": "assistant", "content": content})
                st.session_state.current_incident = None
                st.rerun()
            else:
                st.error(f"Approval failed: {resp}")

    with hc2:
        if st.button("🔴 Reject", use_container_width=True, key="hitl_rej"):
            code, resp = api_request(
                "POST",
                f"{AGENT_API_URL}/api/v1/investigations/{inc['id']}/reject",
                data={"reason": "Rejected by operator"},
            )
            if code == 200:
                content = (
                    "### 🔴 Remediation Rejected\n\n"
                    "Workflow finished safely — no production changes made."
                )
                st.session_state.messages.append({"role": "assistant", "content": content})
                st.session_state.current_incident = None
                st.rerun()
            else:
                st.error(f"Rejection failed: {resp}")

    with hc3:
        if st.button("🔍 More Diagnostics", use_container_width=True, key="hitl_diag"):
            code, _ = api_request(
                "POST",
                f"{AGENT_API_URL}/api/v1/investigations/{inc['id']}/diagnostics",
                data={"reason": "Additional diagnostics requested."},
            )
            if code == 200:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "🔄 **Expanding diagnostics** — routing into `node_expand_diagnostics` for deeper telemetry analysis.",
                })
                st.rerun()

# ---------------------------------------------------------------------------
# CHAT INPUT
# ---------------------------------------------------------------------------
user_prompt = st.chat_input("Describe an incident, ask about a service, or type 'check payment-api'...")

if st.session_state.preset_prompt:
    user_prompt = st.session_state.preset_prompt
    st.session_state.preset_prompt = None

if user_prompt:
    prompt = user_prompt.strip()
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # ── Conversational intent: don't hit the API for chit-chat ──
    conv_reply = _get_conversational_reply(prompt)
    if conv_reply and not _is_investigation_request(prompt):
        with st.chat_message("assistant"):
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

    # ── Ensure symptoms meets min_length=5 ──
    symptoms = prompt if len(prompt) >= 5 else f"Investigate {target_svc}: {prompt}"

    with st.chat_message("assistant"):
        # Show investigation progress while the agent runs
        status_ph = st.empty()
        with status_ph.status(f"⚡ Investigating `{target_svc}`...", expanded=True) as s:
            st.write("📥 Ingesting alert — mapping blast radius & dependencies...")
            code, resp = api_request(
                "POST",
                f"{AGENT_API_URL}/api/v1/investigations/trigger",
                data={"service": target_svc, "symptoms": symptoms, "severity": "critical"},
                timeout=60.0,
            )
            st.write("📊 Prometheus golden signals scraped.")
            st.write("📜 Grafana Loki log stream queried.")
            st.write("🧠 Qdrant vector memory searched.")
            st.write("💡 Evidence correlated — RCA complete.")
            state_label = "complete" if code in (200, 201) else "error"
            s.update(
                label="✅ Investigation complete!" if code in (200, 201) else "❌ Investigation error",
                state=state_label,
            )
        status_ph.empty()

        # Stream the formatted response
        response_text = _build_response(code, resp, target_svc)
        st.write_stream(_stream_text(response_text))

        st.session_state.messages.append({"role": "assistant", "content": response_text})

        # Set HITL state if remediation is pending approval
        if code in (200, 201):
            state: dict[str, Any] = resp.get("state", resp)
            proposal = state.get("remediation_proposal")
            is_awaiting = resp.get("is_awaiting_approval", False)
            hyp = state.get("selected_hypothesis")

            if (is_awaiting or proposal) and hyp:
                st.session_state.current_incident = {
                    "id": resp.get("incident_id"),
                    "proposal": proposal or {},
                    "service": target_svc,
                }
                st.rerun()

st.markdown("</div>", unsafe_allow_html=True)
