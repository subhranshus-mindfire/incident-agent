# LangGraph Architecture & State Schema

This document provides the formal architecture specification for the **Autonomous Incident Investigation & Root Cause Analysis Agent**, including the LangGraph execution graph, conditional edges, Human-in-the-Loop (HITL) interrupt gates, and complete state schema contract.

---

## 1. LangGraph State Machine Architecture

The agent executes as a stateful, compiled LangGraph graph persisted via PostgreSQL checkpoints.

```mermaid
flowchart TD
    START([Incident Ingested]) --> IngestAlert[node_ingest_alert]
    IngestAlert --> GatherTelemetry[node_gather_telemetry]
    GatherTelemetry --> CorrelateEvidence[node_correlate_evidence]
    
    CorrelateEvidence --> RouteSufficiency{Evidence Sufficient?}
    RouteSufficiency -- "No (insufficient)" --> ExpandDiagnostics[node_expand_diagnostics]
    ExpandDiagnostics --> CorrelateEvidence
    RouteSufficiency -- "Yes (sufficient)" --> FormulateRCA[node_formulate_rca]
    
    FormulateRCA --> AssessBlastRadius[node_assess_blast_radius]
    AssessBlastRadius --> ProposeRemediation[node_propose_remediation]
    
    ProposeRemediation --> ApprovalGate[node_approval_gate<br/><b>INTERRUPT (HITL)</b>]
    
    ApprovalGate --> RouteApproval{Human Decision}
    RouteApproval -- "APPROVED" --> ExecuteRemediation[node_execute_remediation]
    RouteApproval -- "REJECTED" --> AbortRemediation[node_abort_remediation]
    RouteApproval -- "DIAGNOSTICS_REQUESTED" --> ExpandDiagnostics
    
    ExecuteRemediation --> VerifyHealth[node_verify_health]
    VerifyHealth --> RouteVerification{Health Verified?}
    RouteVerification -- "Degraded (Retry)" --> ExecuteRemediation
    RouteVerification -- "Healthy" --> GeneratePostmortem[node_generate_postmortem]
    
    AbortRemediation --> GeneratePostmortem
    GeneratePostmortem --> PersistMemory[persist_resolved_incident<br/>to Qdrant]
    PersistMemory --> END([Investigation Concluded])
```

---

## 2. Documented State Schema (`InvestigationState`)

The state schema strictly implements all 16 fields mandated by Section 8 of the assignment specification:

| Field | Type | Description |
| :--- | :--- | :--- |
| `incident_id` | `str` | Unique UUID tracking the incident and checkpoint thread. |
| `messages` | `list[AnyMessage]` | LangChain message history representing the investigation trajectory. |
| `severity` | `IncidentSeverity` | Incident classification (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`). |
| `affected_services` | `list[str]` | Target service and calculated upstream/downstream blast radius. |
| `log_findings` | `list[LogSignature]` | Aggregated error log signatures, counts, and sample lines from Loki. |
| `metrics` | `TelemetrySummary` | Prometheus Golden Signals (5xx error rate, p95 latency, requests/s, CPU, memory). |
| `deployments` | `list[DeploymentRecord]` | Recent releases, tags, deployment timestamps, and commit SHAs. |
| `retrieved_incidents` | `list[HistoricalIncident]` | Semantically similar past incident postmortems retrieved from Qdrant vector memory. |
| `hypotheses` | `list[Hypothesis]` | Ranked root-cause hypotheses with confidence scores and supporting evidence. |
| `evidence` | `list[str]` | Normalized, correlated telemetry findings linking logs, metrics, and releases. |
| `pending_action` | `str \| None` | The high-risk remediation action awaiting human approval. |
| `approval_status` | `ApprovalStatus` | Current HITL state (`PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `AUTO_APPROVED`). |
| `executed_actions` | `list[str]` | History of executed remediation actions (prevents duplicate execution upon retries). |
| `retry_count` | `int` | Counter tracking retry attempts for diagnostic loops and health checks. |
| `errors` | `list[str]` | Log of runtime exceptions or tool connection warnings encountered during execution. |
| `verification_results` | `dict[str, Any]` | Post-remediation health metrics proving service recovery. |
| `postmortem` | `str \| None` | Complete Markdown Root Cause Analysis (RCA) postmortem document. |

---

## 3. The 7 Required Functional Tools

| Tool | Signature | Source / Target |
| :--- | :--- | :--- |
| `fetch_application_logs` | `(service: str, time_range_minutes: int) -> list[LogSignature]` | Live Grafana Loki (`http://loki:3100/loki/api/v1/query_range`) with secret redaction and token bounding. |
| `get_system_metrics` | `(service: str) -> TelemetrySummary` | Live Prometheus (`http://prometheus:9090`) PromQL queries for 5xx rates, latencies, and resource saturation. |
| `get_recent_deployments` | `(service: str) -> list[DeploymentRecord]` | Live microservice HTTP registry (`http://payment-api:8080/deployments`). |
| `search_past_incidents` | `(query: str, service: str \| None, limit: int) -> list[HistoricalIncident]` | Qdrant vector database (`historical_incidents` collection) with 384-dimensional cosine similarity. |
| `get_service_dependencies`| `(service: str) -> ServiceDependencyMap` | Architectural topology mapping upstream and downstream service dependencies. |
| `execute_remediation` | `(action: str, service: str, approval_id: str \| None) -> RemediationExecutionResult` | Live remediation triggers on `payment-api` (`/remediation/rollback`, `/remediation/kill-queries`, `/remediation/restart`). |
| `create_incident_report` | `(incident_state: InvestigationState) -> PostmortemReport` | Markdown postmortem generation engine formatted with timeline, root cause, and long-term action items. |

---

## 4. Human-in-the-Loop (HITL) Workflow

1. When the agent formulates a remediation action (e.g. `ROLLBACK_DEPLOYMENT` or `TERMINATE_DB_TRANSACTIONS`), the graph assesses the blast radius and risk tier.
2. If the action is high-risk, `node_approval_gate` triggers a **LangGraph interrupt**:
   - The execution halts before applying changes.
   - The incident state is durably saved in PostgreSQL (`checkpoint_writes` and `checkpoint_blobs`).
   - The API and UI present the proposed action, rationale, risk tier, and rollback plan.
3. The human operator can:
   - **Approve:** Resumes execution from the exact checkpoint without re-running previous gathering steps.
   - **Reject:** Aborts the action and moves to postmortem documenting the rejection.
   - **Request Diagnostics:** Routes back through `node_expand_diagnostics` to gather deeper metrics and logs.
4. **Idempotency Guard:** `executed_actions` prevents repeated executions of write actions during recovery or retries.
