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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("incident_agent.ui")

# Environment endpoints
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")
PAYMENT_API_URL = os.getenv("PAYMENT_API_URL", "http://localhost:8080").rstrip("/")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100").rstrip("/")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")


# ---------------------------------------------------------------------------
# Streamlit Application Configuration & Layout
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="AI Incident Investigation & Root Cause Analysis Agent",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .metric-card {
        background-color: #1E222A;
        border-radius: 8px;
        padding: 16px;
        border: 1px solid #30363D;
        margin-bottom: 12px;
    }
    .status-badge {
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 12px;
        display: inline-block;
    }
    .badge-critical { background-color: #8B0000; color: #FFF; }
    .badge-high { background-color: #D97706; color: #FFF; }
    .badge-approved { background-color: #059669; color: #FFF; }
    .badge-pending { background-color: #D97706; color: #FFF; animation: pulse 2s infinite; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🚨 Autonomous Incident Investigation & RCA Agent")
st.caption(
    "Live LangGraph state machine, real-time telemetry (Prometheus/Loki), Qdrant memory, "
    "and Human-in-the-Loop approval gate."
)

# Session state initialization
if "active_incident_id" not in st.session_state:
    st.session_state["active_incident_id"] = None
if "last_investigation_state" not in st.session_state:
    st.session_state["last_investigation_state"] = None
if "chaos_message" not in st.session_state:
    st.session_state["chaos_message"] = None


# ---------------------------------------------------------------------------
# SIDEBAR: Infrastructure Health & Live Chaos Injection
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🖥️ System Infrastructure")
    col_a, col_b = st.columns(2)

    with col_a:
        app_ok = ping_endpoint(f"{AGENT_API_URL}/health")
        st.markdown(f"**Agent API:** {'🟢 Online' if app_ok else '🔴 Offline'}")

        pay_ok = ping_endpoint(f"{PAYMENT_API_URL}/health")
        st.markdown(f"**Payment API:** {'🟢 Online' if pay_ok else '🔴 Degraded'}")

        prom_ok = ping_endpoint(f"{PROMETHEUS_URL}/-/healthy")
        st.markdown(f"**Prometheus:** {'🟢 Online' if prom_ok else '🔴 Offline'}")

    with col_b:
        loki_ok = ping_endpoint(f"{LOKI_URL}/ready")
        st.markdown(f"**Loki Logs:** {'🟢 Online' if loki_ok else '🔴 Offline'}")

        qdrant_ok = ping_endpoint(f"{QDRANT_URL}/collections")
        st.markdown(f"**Qdrant Vector:** {'🟢 Online' if qdrant_ok else '🔴 Offline'}")

    st.divider()

    st.header("⚡ Live Chaos Controller")
    st.caption("Inject production failure modes into payment-api and stream real telemetry.")

    scenario = st.selectbox(
        "Select Chaos Scenario:",
        [
            "Database Connection Pool Deadlock",
            "Bad Deployment v2.3.1 (DEP-101 Regression)",
            "High Latency / CPU Saturation",
        ],
    )

    traffic_count = st.slider("Payment Requests to Send:", min_value=5, max_value=30, value=10)

    col_c1, col_c2 = st.columns(2)

    with col_c1:
        if st.button("🔥 Inject Chaos & Fail", use_container_width=True):
            with st.spinner("Injecting fault and generating real-time error traffic..."):
                if "Database" in scenario:
                    api_request("POST", f"{PAYMENT_API_URL}/chaos/db-deadlock")
                elif "Deployment" in scenario:
                    api_request("POST", f"{PAYMENT_API_URL}/chaos/bad-deployment")
                else:
                    api_request("POST", f"{PAYMENT_API_URL}/chaos/cpu-burn")

                # Send traffic
                errors = 0
                for idx in range(traffic_count):
                    code, _ = api_request(
                        "POST",
                        f"{PAYMENT_API_URL}/pay",
                        data={"amount": 49.99 + idx, "currency": "USD", "account_id": f"acc-{idx}"},
                        timeout=3.0,
                    )
                    if code >= 500:
                        errors += 1
                st.session_state["chaos_message"] = (
                    f"⚠️ Chaos injected! {errors}/{traffic_count} requests failed with HTTP 500. "
                    "Logs pushed to Loki and Prometheus metrics updated."
                )

    with col_c2:
        if st.button("🔄 Clear All Faults", use_container_width=True):
            api_request("POST", f"{PAYMENT_API_URL}/chaos/clear")
            st.session_state["chaos_message"] = "✅ All chaos cleared. payment-api restored to healthy state."

    if st.session_state["chaos_message"]:
        st.info(st.session_state["chaos_message"])


# ---------------------------------------------------------------------------
# MAIN AREA: Tabs for Intake, Investigation Console, and Postmortem Report
# ---------------------------------------------------------------------------
tab_intake, tab_investigation, tab_postmortem = st.tabs(
    ["🚨 Trigger Incident", "🔍 Investigation & HITL Console", "📋 Structured RCA Postmortem"]
)


# ===========================================================================
# TAB 1: Trigger Incident
# ===========================================================================
with tab_intake:
    st.subheader("Initiate AI Incident Investigation")
    st.write(
        "Trigger the autonomous LangGraph workflow to ingest alerts, gather telemetry, "
        "correlate evidence, formulate RCA hypotheses, and propose remediation."
    )

    with st.form("trigger_incident_form"):
        col1, col2 = st.columns(2)
        with col1:
            service_input = st.selectbox(
                "Target Microservice:",
                ["payment-api", "order-service", "auth-service"],
                index=0,
            )
            severity_input = st.selectbox(
                "Incident Severity:",
                ["critical", "high", "medium", "low"],
                index=0,
            )

        with col2:
            preset = st.selectbox(
                "Quick Symptoms Preset:",
                [
                    "Custom Symptoms",
                    "payment-api ERROR 500: Database connection timeout waiting for connection; pool exhausted",
                    "payment-api ERROR 500: Fatal regression introduced in DEP-101 (v2.3.1)",
                ],
            )

        if preset == "Custom Symptoms":
            default_symptoms = (
                "Our payment API is returning HTTP 500 errors. Investigate logs and recent deployments, "
                "identify probable root causes, and recommend a fix."
            )
        else:
            default_symptoms = preset

        symptoms_input = st.text_area("Observed Symptoms / Alert Description:", value=default_symptoms, height=100)

        submitted = st.form_submit_button("🚀 Start Autonomous Investigation", type="primary", use_container_width=True)

        if submitted:
            with st.spinner("Invoking LangGraph Investigation Agent..."):
                status_code, response = api_request(
                    "POST",
                    f"{AGENT_API_URL}/api/v1/investigations/trigger",
                    data={
                        "service": service_input,
                        "symptoms": symptoms_input,
                        "severity": severity_input,
                    },
                )

                if status_code in (200, 201):
                    inc_id = response.get("incident_id")
                    st.session_state["active_incident_id"] = inc_id
                    st.session_state["last_investigation_state"] = response
                    st.success(f"✅ Investigation started successfully! Incident ID: `{inc_id}`")
                    st.info("👉 Switch to the **Investigation & HITL Console** tab to view live evidence and approve remediation.")
                else:
                    st.error(f"❌ Failed to trigger investigation (HTTP {status_code}): {response}")


# ===========================================================================
# TAB 2: Live Investigation & HITL Console
# ===========================================================================
with tab_investigation:
    st.subheader("Live Investigation & Human-in-the-Loop Review")

    top_c1, top_c2 = st.columns([3, 1])
    with top_c1:
        current_id = st.text_input(
            "Active Incident UUID:",
            value=st.session_state.get("active_incident_id") or "",
            placeholder="Enter incident ID or trigger a new one above",
        )
    with top_c2:
        st.write("")
        st.write("")
        refresh_btn = st.button("🔄 Refresh State", use_container_width=True)

    if current_id:
        st.session_state["active_incident_id"] = current_id

        # Fetch state from FastAPI backend
        code, live_data = api_request("GET", f"{AGENT_API_URL}/api/v1/investigations/{current_id}")

        if code == 200:
            state = live_data.get("state", live_data)
            is_awaiting_approval = live_data.get("is_awaiting_approval", False)
            approval_status = state.get("approval_status", "UNKNOWN")

            # Status Banner
            status_color = "red" if is_awaiting_approval else "green"
            st.markdown(
                f"### State: <span style='color:{status_color}; font-weight:bold;'>{approval_status}</span> "
                f"(Status: `{state.get('status', 'RUNNING')}`)",
                unsafe_allow_html=True,
            )

            # ---------------------------------------------------------------
            # HUMAN-IN-THE-LOOP (HITL) APPROVAL GATE
            # ---------------------------------------------------------------
            proposal = state.get("remediation_proposal") or {}
            pending_action = state.get("pending_action") or proposal.get("action_type")

            if is_awaiting_approval or approval_status == "PENDING_APPROVAL":
                st.warning("⚠️ **HUMAN APPROVAL REQUIRED BEFORE EXECUTION**")
                with st.container():
                    st.markdown(
                        f"""
                        **Proposed Action:** `{pending_action or 'ROLLBACK_DEPLOYMENT'}`  
                        **Target Service:** `{state.get('service', 'payment-api')}`  
                        **Risk Tier:** `{proposal.get('risk_tier', 'CRITICAL')}`  
                        **Rationale:** {proposal.get('rationale', 'Remediate detected root cause to restore 200 OK responses.')}  
                        **Rollback Plan:** {proposal.get('rollback_plan', 'Revert changes and restore original version')}
                        """
                    )

                    operator_name = st.text_input("Reviewer Identity:", value="oncall-sre@company.com")
                    decision_notes = st.text_input("Decision Notes / Context:", value="Approved based on telemetry and Loki logs.")

                    btn_c1, btn_c2, btn_c3 = st.columns(3)

                    with btn_c1:
                        if st.button("🟢 Approve Remediation", type="primary", use_container_width=True):
                            with st.spinner("Submitting approval and resuming LangGraph execution..."):
                                app_code, app_resp = api_request(
                                    "POST",
                                    f"{AGENT_API_URL}/api/v1/investigations/{current_id}/approve",
                                    data={"reason": f"Approved by {operator_name}: {decision_notes}"},
                                )
                                if app_code == 200:
                                    st.success("✅ Remediation approved and executed successfully!")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to approve: {app_resp}")

                    with btn_c2:
                        if st.button("🔴 Reject Remediation", use_container_width=True):
                            with st.spinner("Rejecting remediation proposal..."):
                                rej_code, rej_resp = api_request(
                                    "POST",
                                    f"{AGENT_API_URL}/api/v1/investigations/{current_id}/reject",
                                    data={"reason": f"Rejected by {operator_name}: {decision_notes}"},
                                )
                                st.info("Remediation proposal was rejected.")
                                st.rerun()

                    with btn_c3:
                        if st.button("🟡 Request More Diagnostics", use_container_width=True):
                            with st.spinner("Looping back for expanded diagnostics..."):
                                diag_code, diag_resp = api_request(
                                    "POST",
                                    f"{AGENT_API_URL}/api/v1/investigations/{current_id}/diagnostics",
                                    data={"reason": "Additional diagnostic telemetry required."},
                                )
                                st.info("Looping back into investigation pipeline...")
                                st.rerun()

            elif approval_status in ("APPROVED", "AUTO_APPROVED"):
                st.success(f"✅ Remediation `{pending_action}` was Approved & Executed.")
                exec_result = state.get("execution_result") or {}
                if exec_result:
                    st.json(exec_result)

            st.divider()

            # ---------------------------------------------------------------
            # EVIDENCE & TELEMETRY TABS
            # ---------------------------------------------------------------
            st.subheader("Diagnostic Evidence & Telemetry Findings")
            e_tab1, e_tab2, e_tab3, e_tab4, e_tab5 = st.tabs(
                [
                    "📊 Prometheus Metrics",
                    "📜 Loki Logs",
                    "🚀 Deployments",
                    "🧠 Qdrant Memory",
                    "💡 RCA Hypotheses",
                ]
            )

            with e_tab1:
                metrics = state.get("telemetry_summary") or state.get("metrics") or {}
                m_c1, m_c2, m_c3, m_c4 = st.columns(4)
                m_c1.metric("5xx Error Rate", f"{metrics.get('http_error_rate_pct', 0.0):.1f}%")
                m_c2.metric("p99 Latency", f"{metrics.get('p99_latency_seconds', 0.0):.2f}s")
                m_c3.metric("Request Rate", f"{metrics.get('request_rate_per_sec', 0.0):.1f} req/s")
                m_c4.metric("CPU Saturation", f"{metrics.get('cpu_usage_pct', 0.0):.1f}%")

                anomalies = metrics.get("detected_anomalies", [])
                if anomalies:
                    st.write("**Detected Anomalies:**")
                    for anom in anomalies:
                        st.markdown(f"- ⚠️ {anom}")

            with e_tab2:
                logs = state.get("log_signatures") or state.get("log_findings") or []
                if logs:
                    for log in logs:
                        count = log.get("count", 1)
                        sample = log.get("sample_line", "")
                        st.code(f"[{count} occurrences] {sample}", language="log")
                else:
                    st.info("No error log signatures detected.")

            with e_tab3:
                deployments = state.get("recent_deployments") or state.get("deployments") or []
                if deployments:
                    st.dataframe(deployments, use_container_width=True)
                else:
                    st.info("No recent deployments returned.")

            with e_tab4:
                incidents = state.get("historical_incidents") or state.get("retrieved_incidents") or []
                if incidents:
                    for inc in incidents:
                        score = inc.get("similarity_score", 0.0)
                        st.markdown(
                            f"**{inc.get('incident_id')}** — *Similarity: {score:.2f}*  \n"
                            f"**Root Cause:** {inc.get('root_cause')}  \n"
                            f"**Remediation:** `{inc.get('remediation')}`  \n"
                            f"**Outcome:** {inc.get('outcome')}"
                        )
                        st.divider()
                else:
                    st.info("No past matching incidents found in Qdrant memory.")

            with e_tab5:
                hypotheses = state.get("hypotheses") or []
                if hypotheses:
                    for h in hypotheses:
                        conf = h.get("confidence", 0.0) * 100
                        st.markdown(f"#### {h.get('title')} ({conf:.0f}% Confidence)")
                        st.write(h.get("description"))
                        st.caption(f"Category: {h.get('category')} | Supporting Evidence: {', '.join(h.get('supporting_evidence', []))}")
                        st.divider()
                else:
                    st.info("Hypotheses generation pending.")

        else:
            st.error(f"Could not load state for incident `{current_id}` (HTTP {code}).")


# ===========================================================================
# TAB 3: Structured RCA Postmortem
# ===========================================================================
with tab_postmortem:
    st.subheader("Structured Root Cause Analysis (RCA) Postmortem")

    if st.session_state.get("active_incident_id"):
        cur_id = st.session_state["active_incident_id"]
        c, live_data = api_request("GET", f"{AGENT_API_URL}/api/v1/investigations/{cur_id}")
        state = live_data.get("state", live_data) if c == 200 else {}
        postmortem = state.get("postmortem")

        if postmortem:
            st.markdown(postmortem)

            st.download_button(
                label="📥 Download Structured RCA Postmortem (.md)",
                data=postmortem,
                file_name=f"RCA-Postmortem-{cur_id}.md",
                mime="text/markdown",
            )
        else:
            st.info(
                "Postmortem report will be automatically generated upon remediation approval and health verification."
            )
    else:
        st.info("No active investigation selected. Select an incident in the Investigation Console.")
