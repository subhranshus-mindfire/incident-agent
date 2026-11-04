"""Severity classification from the symptom text, used when the caller does not state a severity."""

from typing import Final

from app.constants.enums import IncidentSeverity

CRITICAL_TERMS: Final = (
    "outage",
    " down",
    "unavailable",
    "data loss",
    "all requests failing",
    "total failure",
)
HIGH_TERMS: Final = (
    "500",
    "error",
    "timeout",
    "exhaust",
    "degraded",
    "slow",
    "latency",
    "crash",
    "failure",
    "deadlock",
    "regression",
)


def classify_severity(symptoms: str) -> IncidentSeverity:
    text = f" {symptoms.lower()} "
    if any(term in text for term in CRITICAL_TERMS):
        return IncidentSeverity.CRITICAL
    if any(term in text for term in HIGH_TERMS):
        return IncidentSeverity.HIGH
    return IncidentSeverity.MEDIUM
