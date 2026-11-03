"""Tool-calling chat agent.

The model decides which live tool to call; every fact in its answer must come from a tool result.
Tools that cannot reach their data source return an explicit error, never invented values.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
from groq import BadRequestError
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from app.config.config import get_settings
from app.config.database import async_session_factory
from app.constants.enums import IncidentSeverity
from app.constants.live import MAX_WINDOW_SECONDS, MIN_WINDOW_SECONDS
from app.constants.llm import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_TURNS,
    MAX_LIST_ROWS,
    MAX_OUTPUT_TOKENS,
    MAX_TOOL_CALL_ATTEMPTS,
    MAX_TOOL_ROUNDS,
)
from app.constants.service_dependencies import SERVICE_DEPENDENCIES
from app.constants.services import PRIMARY_SERVICE
from app.llms.providers import ProviderNotConfiguredError, build_chat_model, is_rate_limit_error
from app.prompts.loader import load_prompt
from app.services.chat_router import route_message
from app.services.clients import get_loki_service, get_prometheus_service
from app.services.investigation_service import InvestigationService, summarize_trigger
from app.services.qdrant_service import get_shared_qdrant_service
from app.tools.investigation_tools import get_recent_deployments, search_past_incidents
from app.utils.errors import error_payload
from app.utils.time import clamp_seconds

logger = logging.getLogger("incident_agent.llms.agent")


CHAT_SYSTEM_PROMPT = load_prompt("chat_agent")


@tool
async def get_live_golden_signals(service: str, window_seconds: int = 60) -> dict[str, Any]:
    """Live Prometheus golden signals for a service over the last window_seconds (10 to 3600).

    Returns 5xx error rate (percent), request rate (per second), p95 latency (ms) and CPU (percent).
    A request rate of 0 means no traffic in the window.
    """
    window = clamp_seconds(window_seconds, MIN_WINDOW_SECONDS, MAX_WINDOW_SECONDS)
    try:
        signals = await get_prometheus_service().get_golden_signals(
            service=service, window_seconds=window
        )
    except Exception as exc:
        return error_payload(exc)
    return {**signals.model_dump(mode="json"), "window_seconds": window}


@tool
async def get_live_logs(service: str, window_seconds: int = 300, limit: int = 15) -> dict[str, Any]:
    """Real Loki log lines for a service over the last window_seconds, newest first.

    An empty list means Loki has no lines for that service in the window.
    """
    window = clamp_seconds(window_seconds, MIN_WINDOW_SECONDS, MAX_WINDOW_SECONDS)
    now = datetime.now(UTC)
    try:
        result = await get_loki_service().query_range(
            logql=f'{{service="{service}"}}',
            start=now - timedelta(seconds=window),
            end=now,
            limit=max(1, min(limit, 200)),
            deduplicate=False,
        )
    except Exception as exc:
        return error_payload(exc)
    entries = [e for stream in result.streams for e in stream.entries]
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    lines = [
        {"time": e.timestamp.isoformat(), "level": e.level, "line": e.line}
        for e in entries[: max(1, min(limit, 200))]
    ]
    return {
        "service": service,
        "window_seconds": window,
        "total_lines": len(entries),
        "lines": lines,
    }


@tool
async def get_deployments(service: str) -> dict[str, Any]:
    """Recent deployments (version, status, time) for a service, from the deployment API."""
    try:
        records = await get_recent_deployments(service)
    except Exception as exc:
        return error_payload(exc)
    return {"service": service, "deployments": [r.model_dump(mode="json") for r in records]}


@tool
async def search_incident_memory(query: str) -> dict[str, Any]:
    """Semantic search over resolved past incidents stored in Qdrant. Returns similar incidents with root causes."""
    try:
        matches = await search_past_incidents(query=query, limit=3)
    except Exception as exc:
        return error_payload(exc)
    return {
        "matches": [
            {k: v for k, v in m.model_dump(mode="json").items() if k != "incident_id"}
            for m in matches
        ]
    }


@tool
async def start_investigation(service: str, symptoms: str) -> dict[str, Any]:
    """Open a full incident investigation for a service. Creates an incident record, gathers evidence,
    and proposes a remediation that waits for human approval. Use only when the user asks to investigate,
    diagnose or fix a fault."""
    incident_id = str(uuid4())
    try:
        async with async_session_factory() as session:
            investigation = InvestigationService(session=session)
            result = await investigation.start_investigation(
                incident_id=incident_id,
                service=service,
                symptoms=symptoms[:500],
                severity=IncidentSeverity.CRITICAL,
            )
    except Exception as exc:
        return error_payload(exc)
    summary = summarize_trigger(incident_id, service, result)
    state = summary["state"]
    return {
        "incident_id": incident_id,
        "awaiting_approval": summary["is_awaiting_approval"],
        "root_cause": state["selected_hypothesis"],
        "remediation_proposal": summary["remediation_proposal"],
        "log_findings": state["log_findings"],
        "metrics": state["metrics"],
        "recent_deployments": state["deployments"],
        "similar_incidents": state["retrieved_incidents"],
        "affected_services": state["affected_services"],
    }


@tool
async def get_service_dependencies(service: str) -> dict[str, Any]:
    """Upstream services (they depend on this service) and downstream services (this service depends on),
    from the service dependency map. Use for dependency and blast-radius questions."""
    mapping = SERVICE_DEPENDENCIES.get(service)
    if mapping is None:
        return {
            "service": service,
            "known": False,
            "error": "no dependency map entry for this service",
        }
    return {"known": True, **mapping.model_dump()}


@tool
async def get_service_health(service: str) -> dict[str, Any]:
    """Health endpoint status and active fault flags for a service. Works without traffic.

    Use this first to decide whether a service is up. Zero traffic does not mean healthy.
    """
    if service != PRIMARY_SERVICE:
        return {"service": service, "error": "no health endpoint is configured for this service"}
    target_url = os.getenv("PAYMENT_API_URL", "http://payment-api:8080")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{target_url}/health")
            res.raise_for_status()
    except httpx.HTTPError as exc:
        return {"service": service, "reachable": False, **error_payload(exc)}
    return {"service": service, "reachable": True, **res.json()}


@tool
async def list_stored_incidents(
    service: str = "", status: str = "", limit: int = 20
) -> dict[str, Any]:
    """List stored incidents, newest first, with ID, title, service, status and dates.

    Use this to list or count past incidents. Optional filters: service name and status (for example
    "resolved"). Each entry says whether the incident is also in long-term memory (Qdrant).
    """
    base_url = os.getenv("AGENT_SELF_URL", "http://localhost:8000").rstrip("/")
    params: dict[str, Any] = {"limit": 100}  # the API's maximum; trimmed to `limit` below
    if service:
        params["service"] = service
    if status:
        params["status"] = status
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{base_url}/api/v1/incidents", params=params)
            res.raise_for_status()
            rows = res.json()
    except Exception as exc:
        return error_payload(exc)
    try:
        memory_ids: (
            set[str] | None
        ) = await get_shared_qdrant_service().list_historical_incident_ids()
    except Exception as exc:
        logger.warning(f"Could not read incident memory: {exc}")
        memory_ids = None
    rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    total_found = len(rows)
    # Keep tool output small: the model's per-minute token limit is far below 100 full records.
    rows = rows[: max(1, min(limit, MAX_LIST_ROWS))]
    incidents = [
        {
            "title": r.get("title"),
            "service": r.get("service"),
            "status": r.get("status"),
            "created_at": r.get("created_at"),
            "resolved_at": r.get("resolved_at"),
            "in_memory": None if memory_ids is None else r["id"] in memory_ids,
        }
        for r in rows
    ]
    return {
        "total_found": total_found,  # capped at 100 by the API
        "returned": len(incidents),
        "incidents": incidents,
    }


TOOLS = [
    get_service_dependencies,
    list_stored_incidents,
    get_service_health,
    get_live_golden_signals,
    get_live_logs,
    get_deployments,
    search_incident_memory,
    start_investigation,
]
_TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def _message_text(message: BaseMessage) -> str:
    """Plain text of a model reply. Gemini returns a list of content blocks; Groq returns a string."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _is_unknown_tool_error(exc: BadRequestError) -> bool:
    text = str(exc)
    return "tool_use_failed" in text or "tool call validation failed" in text


async def _invoke_model(llm: Any, messages: list[BaseMessage]) -> AIMessage:
    """Calls the model. Retries when it names a tool that does not exist, which the provider rejects."""
    for attempt in range(1, MAX_TOOL_CALL_ATTEMPTS + 1):
        try:
            response: AIMessage = await llm.ainvoke(messages)
            return response
        except BadRequestError as exc:
            if not _is_unknown_tool_error(exc) or attempt == MAX_TOOL_CALL_ATTEMPTS:
                raise
            logger.warning(f"Model called an unknown tool (attempt {attempt}); retrying: {exc}")
    raise RuntimeError("unreachable: the loop returns or raises")


def _to_messages(history: list[dict[str, str]], message: str) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=CHAT_SYSTEM_PROMPT)]
    for item in history[-MAX_HISTORY_TURNS:]:
        if item.get("role") == "assistant":
            messages.append(AIMessage(content=item.get("content", "")[:MAX_HISTORY_CHARS]))
        else:
            messages.append(HumanMessage(content=item.get("content", "")[:MAX_HISTORY_CHARS]))
    messages.append(HumanMessage(content=message))
    return messages


async def run_chat(message: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """Runs one chat turn: fixed or live answers first, otherwise the model calls tools and answers from them."""
    routed = await route_message(message, history)
    if routed.reply is not None:
        return {"reply": routed.reply, "incident": None}
    message = routed.text

    try:
        base_llm = build_chat_model(get_settings(), max_output_tokens=MAX_OUTPUT_TOKENS)
    except ProviderNotConfiguredError as exc:
        return {
            "reply": f"The language model is not configured: {exc}. Set it in .env and restart the app.",
            "incident": None,
        }
    llm = base_llm.bind_tools(TOOLS)

    messages = _to_messages(history, message)
    incident: dict[str, Any] | None = None

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            ai_message = await _invoke_model(llm, messages)
        except Exception as exc:
            if is_rate_limit_error(exc):
                logger.warning(f"Language model rate limit reached: {exc}")
                return {
                    "reply": "The language model's usage limit is reached. Wait a while and ask again.",
                    "incident": incident,
                }
            logger.error(f"Language model call failed: {exc}")
            return {
                "reply": "The language model could not process this request. "
                "Ask a narrower question, for example about one service or a shorter time window.",
                "incident": incident,
            }
        messages.append(ai_message)
        if not ai_message.tool_calls:
            return {"reply": _message_text(ai_message), "incident": incident}

        for call in ai_message.tool_calls:
            tool_fn = _TOOLS_BY_NAME.get(call["name"])
            if tool_fn is None:
                result: Any = {"error": f"unknown tool {call['name']}"}
            else:
                try:
                    result = await tool_fn.ainvoke(call["args"])
                except Exception as exc:  # a bad tool call must not end the whole turn
                    logger.warning(f"Tool {call['name']} failed: {exc}")
                    result = error_payload(exc)
            if (
                call["name"] == "start_investigation"
                and isinstance(result, dict)
                and result.get("incident_id")
            ):
                incident = result
                result = {k: v for k, v in result.items() if k != "incident_id"}
            messages.append(
                ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"])
            )

    # Out of tool rounds: answer from the results already gathered, without offering more tools.
    messages.append(
        HumanMessage(
            content="Stop calling tools. Answer now from the tool results above, and say what is still missing."
        )
    )
    try:
        final = await base_llm.ainvoke(messages)
    except Exception as exc:
        logger.error(f"Final answer call failed: {exc}")
        return {
            "reply": "I could not finish the analysis. Try a narrower question.",
            "incident": incident,
        }
    return {"reply": _message_text(final), "incident": incident}
