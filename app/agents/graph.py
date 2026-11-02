import logging
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.nodes import (
    node_assess_blast_radius,
    node_await_approval,
    node_execute_remediation,
    node_formulate_rca,
    node_gather_telemetry,
    node_generate_postmortem,
    node_ingest_alert,
    node_retrieve_runbooks,
    node_verify_health,
)
from app.schemas.agent_state import ApprovalStatus, InvestigationState

logger = logging.getLogger("incident_agent.agents.graph")


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
) -> Literal["execute_remediation", "generate_postmortem"]:
    """Routes execution based on human decision."""
    status = state.get("approval_status")
    if status in (ApprovalStatus.APPROVED, ApprovalStatus.AUTO_APPROVED):
        logger.info("[Router: ApprovalGate] Action approved -> Proceeding to execution.")
        return "execute_remediation"
    logger.warning(
        "[Router: ApprovalGate] Action rejected or aborted -> Skipping execution to postmortem."
    )
    return "generate_postmortem"


def create_investigation_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Constructs and compiles the enterprise LangGraph Incident Investigation Workflow.

    Features:
    - Directed acyclic state graph with deterministic execution order.
    - Checkpointed state persistence across every node.
    - Human-in-the-Loop interruption gate ('await_approval') for high-blast-radius actions.
    - Post-remediation health verification feedback loop.
    """
    workflow = StateGraph(InvestigationState)

    # 1. Register Nodes
    workflow.add_node("ingest_alert", node_ingest_alert)
    workflow.add_node("gather_telemetry", node_gather_telemetry)
    workflow.add_node("retrieve_runbooks", node_retrieve_runbooks)
    workflow.add_node("formulate_rca", node_formulate_rca)
    workflow.add_node("assess_blast_radius", node_assess_blast_radius)
    workflow.add_node("await_approval", node_await_approval)
    workflow.add_node("execute_remediation", node_execute_remediation)
    workflow.add_node("verify_health", node_verify_health)
    workflow.add_node("generate_postmortem", node_generate_postmortem)

    # 2. Register Edges
    workflow.add_edge(START, "ingest_alert")
    workflow.add_edge("ingest_alert", "gather_telemetry")
    workflow.add_edge("gather_telemetry", "retrieve_runbooks")
    workflow.add_edge("retrieve_runbooks", "formulate_rca")
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

    # Conditional Branching after Human Decision
    workflow.add_conditional_edges(
        "await_approval",
        route_after_approval,
        {
            "execute_remediation": "execute_remediation",
            "generate_postmortem": "generate_postmortem",
        },
    )

    workflow.add_edge("execute_remediation", "verify_health")
    workflow.add_edge("verify_health", "generate_postmortem")
    workflow.add_edge("generate_postmortem", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()

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
