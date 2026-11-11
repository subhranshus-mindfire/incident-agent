from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field

from app.constants.enums import IncidentSeverity, IncidentStatus


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"
    DIAGNOSTICS_REQUESTED = "diagnostics_requested"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RemediationActionType(StrEnum):
    SCALE_UP_REPLICAS = "SCALE_UP_REPLICAS"
    ROLLING_RESTART = "ROLLING_RESTART"
    ROLLBACK_DEPLOYMENT = "ROLLBACK_DEPLOYMENT"
    TERMINATE_DB_TRANSACTIONS = "TERMINATE_DB_TRANSACTIONS"
    ADJUST_CACHE_POLICY = "ADJUST_CACHE_POLICY"
    ENABLE_CIRCUIT_BREAKER = "ENABLE_CIRCUIT_BREAKER"
    MANUAL_ESCALATION = "MANUAL_ESCALATION"


class RCAHypothesis(BaseModel):
    """Structured root cause hypothesis formulated by the reasoning engine."""

    title: str = Field(..., description="Concise title of root cause scenario")
    root_cause: str = Field(..., description="Detailed technical explanation of failure mechanism")
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )
    evidence_citations: list[str] = Field(
        default_factory=list, description="Direct metric/log telemetry citations"
    )
    recommended_action: RemediationActionType = Field(
        default=RemediationActionType.MANUAL_ESCALATION,
        description="Recommended remediation action",
    )


class RemediationProposal(BaseModel):
    """Formal remediation action proposal with blast radius and safety bounds."""

    action_type: RemediationActionType = Field(..., description="Action identifier")
    target_resource: str = Field(..., description="Kubernetes deployment, DB pool, or service name")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Execution parameters")
    risk_tier: RiskTier = Field(..., description="Calculated operational risk level")
    blast_radius: str = Field(..., description="Estimated scope and affected components")
    rollback_plan: str = Field(
        ..., description="Fallback action in case remediation degrades health"
    )
    requires_approval: bool = Field(default=True, description="Whether human approval is mandatory")


class RemediationExecutionResult(BaseModel):
    """Result of remediation action execution."""

    success: bool
    action_type: str
    message: str
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stdout: str = ""


class HealthVerificationReport(BaseModel):
    """Post-remediation stabilization and health verification outcome."""

    stabilized: bool
    previous_error_rate: float
    current_error_rate: float
    previous_latency_ms: float
    current_latency_ms: float
    observation_window_seconds: int
    details: str


class PostmortemReport(BaseModel):
    """Executive postmortem incident summary and prevention plan."""

    incident_id: str
    service: str
    summary: str
    root_cause: str
    timeline: list[str] = Field(default_factory=list)
    remediation_summary: str
    verification_outcome: str
    prevention_action_items: list[str] = Field(default_factory=list)
    markdown_content: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TelemetrySummary(BaseModel):
    """Compact bounded telemetry representation for state efficiency."""

    http_error_rate_pct: float = 0.0
    p99_latency_seconds: float = 0.0
    request_rate_per_sec: float = 0.0
    cpu_usage_pct: float = 0.0
    memory_usage_pct: float = 0.0
    detected_anomalies: list[str] = Field(default_factory=list)
    # True when the window had enough requests for the error rate and latency to be measurements.
    rates_measured: bool = False
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LogSignature(BaseModel):
    """Deduplicated log entry signature to minimize state footprint."""

    sample_line: str
    count: int
    severity: str = "ERROR"


class DeploymentRecord(BaseModel):
    """Recent deployment record representing a release event."""

    deployment_id: str
    service: str
    version: str
    deployed_at: str
    deployed_by: str = "CI/CD Pipeline"
    commit_sha: str = "HEAD"
    status: str = "SUCCESS"


class HistoricalIncident(BaseModel):
    """Historical incident record retrieved from Qdrant vector memory."""

    incident_id: str
    service: str
    symptoms: str
    root_cause: str
    remediation: str
    outcome: str
    similarity_score: float = 0.0


def merge_audit_history(existing: list[str], new_entries: list[str]) -> list[str]:
    """Custom reducer for appending audit events with memory cap."""
    combined = existing + new_entries
    return combined[-50:]  # Retain only the last 50 events to prevent memory bloat


class InvestigationState(TypedDict):
    """Enterprise LangGraph investigation state schema conforming to Section 8.

    Tracks:
    - incident_id, messages, severity, affected_services
    - log_findings, metrics, deployments, retrieved_incidents
    - hypotheses, evidence, pending_action, approval_status, executed_actions
    - retry_count, errors, verification_results, postmortem
    """

    incident_id: str
    service: str
    symptoms: str
    severity: IncidentSeverity
    status: IncidentStatus
    iteration_count: int

    # Core Section 8 tracking fields
    messages: list[str]
    affected_services: list[str]
    log_findings: list[LogSignature]
    metrics: TelemetrySummary | None
    deployments: list[DeploymentRecord]
    retrieved_incidents: list[HistoricalIncident]
    hypotheses: list[RCAHypothesis]
    evidence: list[str]
    downstream_evidence: list[str]
    pending_action: RemediationProposal | None
    approval_status: ApprovalStatus
    approval_reason: str | None
    executed_actions: list[RemediationExecutionResult]
    retry_count: int
    errors: list[str]
    verification_results: HealthVerificationReport | None

    # Telemetry and aliases for backward-compatibility
    telemetry: TelemetrySummary | None
    log_signatures: list[LogSignature]
    matched_runbook_ids: list[str]
    rca_hypotheses: list[RCAHypothesis]
    selected_hypothesis: RCAHypothesis | None
    remediation_proposal: RemediationProposal | None
    execution_result: RemediationExecutionResult | None
    verification_report: HealthVerificationReport | None
    postmortem: PostmortemReport | None

    # Audit trail (bounded via reducer)
    audit_events: Annotated[list[str], merge_audit_history]
    error: str | None
