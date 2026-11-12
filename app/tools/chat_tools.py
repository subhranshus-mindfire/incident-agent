"""Tools the chat agent can call. Each reads live data or starts an investigation."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

import httpx
from langchain_core.tools import tool
from pydantic import BeforeValidator

from app.auth.context import current_actor
from app.config.database import async_session_factory
from app.constants.live import MAX_WINDOW_SECONDS, MIN_WINDOW_SECONDS
from app.constants.llm import (
    MAX_LIST_ROWS,
)
from app.constants.service_dependencies import SERVICE_DEPENDENCIES
from app.constants.services import PRIMARY_SERVICE
from app.schemas.incident import IncidentResponse
from app.services.clients import get_loki_service, get_prometheus_service
from app.services.incident_service import IncidentService
from app.services.investigation_service import InvestigationService, summarize_trigger
from app.services.loki_service import service_selector
from app.services.qdrant_service import get_shared_qdrant_service
from app.tools.investigation_tools import get_recent_deployments, search_past_incidents
from app.utils.errors import error_payload
from app.utils.time import clamp_seconds

logger = logging.getLogger("incident_agent.tools.chat_tools")


def _coerce_service(value: object) -> str:
    """Small models sometimes send the service as an object, such as {"name": "order-service"}, or a list.

    Extracts the first string so the call still reaches the right service.
    """
    if isinstance(value, dict):
        value = next((v for v in value.values() if isinstance(v, str)), "")
    elif isinstance(value, list):
        value = next((v for v in value if isinstance(v, str)), "")
    return str(value).strip()


ServiceName = Annotated[str, BeforeValidator(_coerce_service)]


@tool
async def get_live_golden_signals(service: ServiceName, window_seconds: int = 60) -> dict[str, Any]:
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
async def get_live_logs(
    service: ServiceName, window_seconds: int = 300, limit: int = 15
) -> dict[str, Any]:
    """Real Loki log lines for a service over the last window_seconds, newest first.

    An empty list means Loki has no lines for that service in the window.
    """
    window = clamp_seconds(window_seconds, MIN_WINDOW_SECONDS, MAX_WINDOW_SECONDS)
    now = datetime.now(UTC)
    try:
        result = await get_loki_service().query_range(
            logql=service_selector(service),
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
async def get_deployments(service: ServiceName) -> dict[str, Any]:
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
async def start_investigation(service: ServiceName, symptoms: str) -> dict[str, Any]:
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
                actor=current_actor(),
            )
    except Exception as exc:
        return error_payload(exc)
    summary = summarize_trigger(incident_id, service, result)
    state = summary["state"]
    return {
        "incident_id": incident_id,
        "created_by": current_actor(),
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
async def get_service_dependencies(service: ServiceName) -> dict[str, Any]:
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
async def get_service_health(service: ServiceName) -> dict[str, Any]:
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
    service: ServiceName = "", status: str = "", limit: int = 20
) -> dict[str, Any]:
    """List stored incidents, newest first, with ID, title, service, status and dates.

    Use this to list or count past incidents. Optional filters: service name and status (for example
    "resolved"). Each entry says whether the incident is also in long-term memory (Qdrant).
    """
    try:
        # Read the database directly. Calling the API from here would need a sign-in token this tool does not have.
        async with async_session_factory() as session:
            found = await IncidentService(session).list_incidents(
                service=service or None,
                status=status or None,
                limit=100,  # the listing's maximum; trimmed to `limit` below
            )
            rows = [IncidentResponse.model_validate(i).model_dump(mode="json") for i in found]
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
