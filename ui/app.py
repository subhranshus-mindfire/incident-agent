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


# ---------------------------------------------------------------------------
# ACTIONS — button callbacks run before the page is drawn, so each change shows once
# ---------------------------------------------------------------------------
PRESET_QUESTIONS = [
    "Is payment-api up?",
    "Investigate payment-api HTTP 500 errors and connection pool timeouts",
    "Did deployment DEP-101 introduce a regression on payment-api?",
    "Check golden signals and blast radius for payment-api",
    "Search past incidents for database connection pool exhaustion",
]
WELCOME_PRESETS = [
    (
        "Investigate HTTP 500 errors",
        "Check logs, metrics and recent deploys on payment-api.",
        "Investigate payment-api HTTP 500 errors. Check logs, metrics, and recent deployments.",
    ),
    (
        "Deployment regression",
        "Did DEP-101 cause connection pool exhaustion on payment-api?",
        "Investigate DEP-101 deployment regression on payment-api. Check error rates and Loki stack traces.",
    ),
    (
        "Blast radius",
        "What does a payment-api failure affect upstream and downstream?",
        "Examine service dependencies for payment-api. Identify upstream and downstream affected services.",
    ),
    (
        "Past incidents",
        "Search memory for connection pool timeouts and their fixes.",
        "Search Qdrant vector memory for past incidents matching database connection pool timeout on payment-api.",
    ),
]


def _queue_prompt(text: str) -> None:
    st.session_state.pending_prompt = text


def _new_chat() -> None:
    st.session_state.messages = []
    st.session_state.current_incident = None
    st.session_state.pop("pending_prompt", None)


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


def _approval_outcome(action: str, resp: dict[str, Any]) -> str:
    state = resp.get("state", {})
    exec_res = state.get("execution_result") or {}
    ok = bool(exec_res.get("success", False))
    postmortem = state.get("postmortem") or {}
    postmortem_md = (
        postmortem.get("markdown_content", "") if isinstance(postmortem, dict) else str(postmortem)
    )
    return (
        f"### Remediation {'executed' if ok else 'failed'}\n\n"
        "| Field | Value |\n|-------|-------|\n"
        f"| Action | `{exec_res.get('action_type', action)}` |\n"
        f"| Status | `{'SUCCESS' if ok else 'FAILED'}` |\n"
        f"| Output | {exec_res.get('message', 'No execution result was returned.')} |\n\n"
        f"{_verification_markdown(state.get('verification_report'))}\n\n"
        "Incident indexed into Qdrant vector memory.\n\n---\n\n"
        f"{postmortem_md}"
    )


def _decide(decision: str, reason: str) -> None:
    """Approve, reject or request more diagnostics for the pending remediation. Runs as a button callback."""
    inc = st.session_state.current_incident
    if not inc:
        return
    code, resp = api_request(
        "POST",
        f"{AGENT_API_URL}/api/v1/investigations/{inc['id']}/{decision}",
        data={"reason": reason},
    )
    if _is_stale_gate(code, resp):
        st.session_state.current_incident = None
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "This remediation is no longer waiting for approval. It was already decided, or the workflow has moved on.",
            }
        )
        return
    if code != 200:
        st.session_state.notice = ("error", f"{decision.capitalize()} failed: {resp}")
        return
    if decision == "approve":
        content = _approval_outcome(inc["proposal"].get("action_type", ""), resp)
        st.session_state.current_incident = None
    elif decision == "reject":
        content = (
            "### Remediation rejected\n\nWorkflow finished safely — no production changes made."
        )
        st.session_state.current_incident = None
    else:
        content = "Expanding diagnostics — routing into `node_expand_diagnostics` for deeper telemetry analysis."
    st.session_state.messages.append({"role": "assistant", "content": content})


def _is_stale_gate(code: int, resp: Any) -> bool:
    """True when the API says the investigation is no longer paused at the approval gate."""
    return code == 400 and isinstance(resp, dict) and resp.get("code") == "INVALID_STATE_TRANSITION"


# ---------------------------------------------------------------------------
# RENDERING
# ---------------------------------------------------------------------------
def _render_approval_card(incident_id: str, proposal: dict[str, Any], pending: bool) -> None:
    def field(key: str, default: str) -> str:
        return (
            str(proposal.get(key, default))
            .replace("RemediationActionType.", "")
            .replace("RiskTier.", "")
        )

    st.markdown(
        '<div class="approval-card">'
        '<div class="approval-title">Approval needed before remediation</div>'
        f'<div class="approval-row"><span>Action</span><code>{field("action_type", "ROLLBACK_DEPLOYMENT")}</code></div>'
        f'<div class="approval-row"><span>Risk</span><span>{field("risk_tier", "CRITICAL")}</span></div>'
        f'<div class="approval-row"><span>Rationale</span><span>{field("rationale", "Proposed to resolve detected root cause.")}</span></div>'
        f'<div class="approval-row"><span>Rollback</span><span>{field("rollback_plan", "Revert to previous stable version.")}</span></div>'
        "</div>",
        unsafe_allow_html=True,
    )
    if not pending:
        return
    approve_col, reject_col, diag_col = st.columns([1.5, 1, 1.3])
    with approve_col:
        st.button(
            "Approve & execute",
            type="primary",
            use_container_width=True,
            key=f"approve_{incident_id}",
            on_click=_decide,
            args=("approve", "Approved by operator"),
        )
    with reject_col:
        st.button(
            "Reject",
            use_container_width=True,
            key=f"reject_{incident_id}",
            on_click=_decide,
            args=("reject", "Rejected by operator"),
        )
    with diag_col:
        st.button(
            "More diagnostics",
            use_container_width=True,
            key=f"diagnostics_{incident_id}",
            on_click=_decide,
            args=("diagnostics", "Additional diagnostics requested."),
        )


def _render_history() -> None:
    """Draws the whole conversation in order. Only the pending approval card has working buttons."""
    pending_id = (st.session_state.current_incident or {}).get("id")
    for msg in st.session_state.messages:
        if msg.get("kind") == "approval":
            _render_approval_card(
                msg["incident_id"], msg["proposal"], pending=msg["incident_id"] == pending_id
            )
        else:
            _render_message(msg["role"], msg["content"])


def _answer(prompt: str) -> None:
    """Sends one question to the backend and draws the new exchange. Saved messages are drawn by _render_history."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.markdown(_user_bubble(prompt), unsafe_allow_html=True)
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages[:-1]
        if m.get("role") in ("user", "assistant") and m.get("kind") is None
    ][-20:]
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        with st.spinner("Checking live telemetry… a local model can take a minute."):
            code, resp = api_request(
                "POST",
                f"{AGENT_API_URL}/api/v1/chat",
                data={
                    "message": prompt,
                    "history": history,
                    "approval_pending": st.session_state.current_incident is not None,
                },
                timeout=300.0,
            )
        reply = (
            str(resp.get("reply", ""))
            if code == 200
            else f"❌ The agent request failed (HTTP {code}): {resp}"
        )
        st.write_stream(_stream_text(reply))
    st.session_state.messages.append({"role": "assistant", "content": reply})

    incident = resp.get("incident") if code == 200 else None
    if incident and incident.get("awaiting_approval") and incident.get("remediation_proposal"):
        proposal = incident["remediation_proposal"]
        st.session_state.messages.append(
            {
                "role": "assistant",
                "kind": "approval",
                "incident_id": incident["incident_id"],
                "proposal": proposal,
            }
        )
        st.session_state.current_incident = {"id": incident["incident_id"], "proposal": proposal}
        _render_approval_card(incident["incident_id"], proposal, pending=True)


# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="brand">✦ Incident Agent</div>', unsafe_allow_html=True)
    st.button("＋  New chat", key="new_chat", use_container_width=True, on_click=_new_chat)

    st.markdown('<div class="side-label">Try asking</div>', unsafe_allow_html=True)
    for idx, question in enumerate(PRESET_QUESTIONS):
        st.button(
            question,
            key=f"sq_{idx}",
            use_container_width=True,
            on_click=_queue_prompt,
            args=(question,),
        )

    pay_ok = ping_endpoint(f"{PAYMENT_API_URL}/health")
    dot_color = "#10A37F" if pay_ok else "#EF4444"
    svc_label = "payment-api · online" if pay_ok else "payment-api · offline"
    st.markdown(
        f'<div class="svc-pill"><span class="svc-dot" style="background:{dot_color};"></span>{svc_label}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# PAGE — one ordered pass: welcome or history, then the new exchange
# ---------------------------------------------------------------------------
queued = st.session_state.pop("pending_prompt", None)
typed = st.chat_input("Ask about a service or describe an incident…")
prompt = (queued or typed or "").strip()

if not st.session_state.messages and not prompt:
    st.markdown(
        '<div class="hero"><div class="hero-mark">✦</div>'
        "<h2>What's happening with your services?</h2>"
        "<p>Describe a symptom, ask about a deployment, or check whether a service is up.</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    columns = st.columns(2) + st.columns(2)
    for column, (title, detail, question) in zip(columns, WELCOME_PRESETS, strict=True):
        with column:
            st.button(
                f"{title}\n{detail}",
                key=f"hero_{title}",
                use_container_width=True,
                on_click=_queue_prompt,
                args=(question,),
            )

_render_history()

notice = st.session_state.pop("notice", None)
if notice:
    st.error(notice[1]) if notice[0] == "error" else st.success(notice[1])

if prompt:
    _answer(prompt)
