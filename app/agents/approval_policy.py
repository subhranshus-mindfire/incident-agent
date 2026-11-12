"""Decides which remediation proposals wait for a person and which run on their own."""

from app.constants.enums import IncidentSeverity
from app.schemas.agent_state import RiskTier

# Medium-severity incidents recover without a person when the action is low or medium risk.
_SELF_SERVE_RISK_TIERS = (RiskTier.LOW, RiskTier.MEDIUM)


def needs_human_approval(risk_tier: RiskTier, severity: IncidentSeverity) -> bool:
    """False for medium-severity incidents with low or medium risk. High and critical risk always wait."""
    if severity == IncidentSeverity.MEDIUM and risk_tier in _SELF_SERVE_RISK_TIERS:
        return False
    return True
