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
    # The backend decides how to answer: greeting, live telemetry, or the agent
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
        }
        st.rerun()
