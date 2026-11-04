"""Remediation endpoints on payment-api and the fault-to-action mapping."""

from app.schemas.agent_state import RemediationActionType

# Remediation endpoint on payment-api for each action.
PAYMENT_API_REMEDIATIONS: dict[RemediationActionType, str] = {
    RemediationActionType.ROLLBACK_DEPLOYMENT: "/remediation/rollback",
    RemediationActionType.TERMINATE_DB_TRANSACTIONS: "/remediation/kill-queries",
    RemediationActionType.ROLLING_RESTART: "/remediation/restart",
}

# Which remediation clears each live fault that payment-api reports on /health.
FAULT_REMEDIATIONS: dict[str, RemediationActionType] = {
    "bad_deployment": RemediationActionType.ROLLBACK_DEPLOYMENT,
    "deadlock": RemediationActionType.TERMINATE_DB_TRANSACTIONS,
    "cpu_burn": RemediationActionType.ROLLING_RESTART,
}


# Post-remediation verification: wait for the rollback to settle, then require both signals under threshold.
VERIFY_SETTLE_SECONDS = 5
