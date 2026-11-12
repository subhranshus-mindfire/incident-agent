# ADR 0001: Human approval before live remediation

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

The agent can propose actions that change a live service, such as rolling back a deployment or terminating database transactions. A wrong automated action can make an outage worse, and the agent can be wrong about the cause. Some actions are low risk, such as scaling replicas, and waiting for a person on every one would slow recovery.

## Decision

- Each proposal carries a risk tier (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) and a `requires_approval` flag. The investigation graph sets the flag. Low-risk proposals at medium severity are auto-approved. Everything else waits.
- The graph pauses at `await_approval` and stores its state in PostgreSQL, so a pause survives a restart. A reviewer approves, rejects, or asks for more diagnostics through the investigation routes.
- The approval routes record the signed-in user as the actor, and the investigation card shows who created it and who decided.
- Execution happens only after the workflow's approval-status check. That check is repeated where the action runs: `RemediationExecutor` and the `execute_remediation` tool refuse a live action that requires approval unless the caller passes `approved=True`. Only the graph node passes it, and only after the check.
- A dry run is always allowed, so a proposal can be validated without approval.
- Execution is idempotent. A successful action is recorded in the checkpoint and is not repeated on retry.

## Consequences

- A high-risk action cannot run because a caller skipped the gate. Two independent checks have to be bypassed.
- Waiting for approval is a visible pause, so the investigation can sit for hours. The UI and the API show it as awaiting approval.
- Any signed-in user can currently approve. There is no reviewer role yet, so this decision protects against unreviewed automation, not against an unauthorized person.
- Adding a new action means setting its risk tier correctly. An action marked low risk runs without approval when severity is medium.

## Alternatives considered

- **Always require approval.** Simple, but it blocks the low-risk recovery the agent is meant to speed up.
- **Let the model decide what needs approval.** Rejected. The decision depends on the risk tier, which is set in code, not in the model's output.
