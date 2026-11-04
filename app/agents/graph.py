import logging
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agents.nodes import (
    node_assess_blast_radius,
    node_await_approval,
    node_correlate_evidence,
    node_execute_remediation,
    node_expand_diagnostics,
    node_formulate_rca,
    node_gather_telemetry,
    node_generate_postmortem,
    node_ingest_alert,
    node_persist_incident_memory,
    node_retrieve_qdrant,
    node_verify_health,
)
from app.config.config import settings
from app.schemas.agent_state import ApprovalStatus, InvestigationState

logger = logging.getLogger("incident_agent.agents.graph")


def build_checkpointer() -> BaseCheckpointSaver[Any]:
    """Durable PostgreSQL checkpointer, so paused approvals survive restarts and workers.

    The pool is not opened here: it needs the running event loop, so the app lifespan
    calls open_checkpointer(). Tests use in-memory state and need no database.
    """
    if settings.ENVIRONMENT == "test":
        return MemorySaver()

    # psycopg takes a plain libpq URL, not the SQLAlchemy "+asyncpg" driver form.
    conninfo = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] = AsyncConnectionPool(
        conninfo=conninfo,
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    return AsyncPostgresSaver(pool)


async def open_checkpointer() -> None:
    """Opens the checkpoint pool and creates LangGraph's tables if they are missing."""
    saver = get_investigation_graph().checkpointer
    if isinstance(saver, AsyncPostgresSaver) and isinstance(saver.conn, AsyncConnectionPool):
        await saver.conn.open()
        await saver.setup()
        logger.info("PostgreSQL checkpointer ready for LangGraph investigation state.")


async def close_checkpointer() -> None:
    """Closes the checkpoint pool on shutdown."""
    saver = get_investigation_graph().checkpointer
    if isinstance(saver, AsyncPostgresSaver) and isinstance(saver.conn, AsyncConnectionPool):
        await saver.conn.close()


def route_evidence_sufficiency(
    state: InvestigationState,
) -> Literal["formulate_rca", "expand_diagnostics"]:
    """Conditional Edge: Evaluates whether collected diagnostic evidence is sufficient.
    Always proceeds to RCA after one diagnostic pass; RCA node itself will short-circuit
    if no anomalies are detected (healthy service path).
    """
    evidence = state.get("evidence", [])
    retry_count = state.get("retry_count", 0)

    # After first pass OR if we have evidence, go to RCA.
    # RCA node owns the healthy-service short-circuit logic.
    if len(evidence) >= 2 or retry_count >= 1:
        logger.info(
            f"[Router: EvidenceSufficiency] {len(evidence)} evidence items (retries={retry_count}) -> Proceeding to RCA."
        )
        return "formulate_rca"

    logger.warning(
        f"[Router: EvidenceSufficiency] {len(evidence)} evidence items -> Expanding diagnostics (retry {retry_count + 1})."
    )
    return "expand_diagnostics"


def route_after_blast_radius(
    state: InvestigationState,
) -> Literal["execute_remediation", "await_approval"]:
    """Routes execution based on risk tier and human approval requirement."""
    status = state.get("approval_status")
    if status == ApprovalStatus.AUTO_APPROVED:
        logger.info("[Router: BlastRadius] Low risk action -> Auto-approved for direct execution.")
        return "execute_remediation"
    logger.info(
        "[Router: BlastRadius] High risk action -> Pausing graph for Human-in-the-Loop approval."
    )
    return "await_approval"


def route_after_approval(
    state: InvestigationState,
) -> Literal["execute_remediation", "expand_diagnostics", "generate_postmortem"]:
    """Routes execution based on reviewer decision: approve, reject, or request more diagnostics."""
    status = state.get("approval_status")
    if status in (ApprovalStatus.APPROVED, ApprovalStatus.AUTO_APPROVED):
        logger.info("[Router: ApprovalGate] Action approved -> Proceeding to execution.")
        return "execute_remediation"
    if status == ApprovalStatus.DIAGNOSTICS_REQUESTED:
        logger.info(
            "[Router: ApprovalGate] Operator requested more diagnostics -> Routing back to diagnostics."
        )
        return "expand_diagnostics"

    logger.warning(
        "[Router: ApprovalGate] Action rejected or aborted -> Skipping execution to postmortem."
    )
    return "generate_postmortem"


def create_investigation_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Constructs and compiles the enterprise LangGraph Incident Investigation Workflow.

    Features:
    - Parallel diagnostic telemetry & Qdrant retrieval.
    - Evidence correlation and sufficiency feedback loop.
    - Checkpointed state persistence across every node.
    - Human-in-the-Loop interruption gate ('await_approval') with resume & diagnostic re-entry.
    - Post-remediation health verification feedback loop.
    - Incident memory persistence into Qdrant for continuous learning.
    """
    workflow = StateGraph(InvestigationState)

    # 1. Register Nodes
    workflow.add_node("ingest_alert", node_ingest_alert)
    workflow.add_node("gather_telemetry", node_gather_telemetry)
    workflow.add_node("retrieve_qdrant", node_retrieve_qdrant)
    workflow.add_node("correlate_evidence", node_correlate_evidence)
    workflow.add_node("expand_diagnostics", node_expand_diagnostics)
    workflow.add_node("formulate_rca", node_formulate_rca)
    workflow.add_node("assess_blast_radius", node_assess_blast_radius)
    workflow.add_node("await_approval", node_await_approval)
    workflow.add_node("execute_remediation", node_execute_remediation)
    workflow.add_node("verify_health", node_verify_health)
    workflow.add_node("persist_incident_memory", node_persist_incident_memory)
    workflow.add_node("generate_postmortem", node_generate_postmortem)

    # 2. Register Edges
    workflow.add_edge(START, "ingest_alert")
    workflow.add_edge("ingest_alert", "gather_telemetry")
    workflow.add_edge("gather_telemetry", "retrieve_qdrant")
    workflow.add_edge("retrieve_qdrant", "correlate_evidence")

    # Conditional Branching: Evidence Sufficiency Check
    workflow.add_conditional_edges(
        "correlate_evidence",
        route_evidence_sufficiency,
        {
            "formulate_rca": "formulate_rca",
            "expand_diagnostics": "expand_diagnostics",
        },
    )

    # Diagnostics loop routes back to correlate_evidence
    workflow.add_edge("expand_diagnostics", "correlate_evidence")

    workflow.add_edge("formulate_rca", "assess_blast_radius")

    # Conditional Branching after Blast Radius Assessment
    workflow.add_conditional_edges(
        "assess_blast_radius",
        route_after_blast_radius,
        {
            "execute_remediation": "execute_remediation",
            "await_approval": "await_approval",
        },
    )

    # Conditional Branching after Human Decision (Approve / Reject / Diagnostics Requested)
    workflow.add_conditional_edges(
        "await_approval",
        route_after_approval,
        {
            "execute_remediation": "execute_remediation",
            "expand_diagnostics": "expand_diagnostics",
            "generate_postmortem": "generate_postmortem",
        },
    )

    workflow.add_edge("execute_remediation", "verify_health")
    workflow.add_edge("verify_health", "persist_incident_memory")
    workflow.add_edge("persist_incident_memory", "generate_postmortem")
    workflow.add_edge("generate_postmortem", END)

    saver = checkpointer if checkpointer is not None else build_checkpointer()

    # Compile with interruption gate before 'await_approval'
    return workflow.compile(
        checkpointer=saver,
        interrupt_before=["await_approval"],
    )


_shared_investigation_graph: CompiledStateGraph[Any, Any, Any, Any] | None = None


def get_investigation_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    """Singleton getter for the compiled investigation graph."""
    global _shared_investigation_graph
    if _shared_investigation_graph is None:
        _shared_investigation_graph = create_investigation_graph()
    return _shared_investigation_graph
