from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.constants.enums import IncidentSeverity


class RunbookSection(BaseModel):
    title: str = Field(..., description="Section title")
    content: str = Field(..., description="Guidance or explanation text")
    commands: list[str] = Field(
        default_factory=list, description="Automated or manual CLI commands"
    )


class RunbookBase(BaseModel):
    title: str = Field(
        ..., min_length=3, max_length=200, description="Descriptive title of the runbook"
    )
    description: str = Field(
        ..., min_length=10, description="Overview of the failure scenario addressed"
    )
    service: str = Field(default="generic", description="Associated service or 'generic'")
    incident_types: list[str] = Field(
        ...,
        min_length=1,
        description="Incident signatures matching this runbook (e.g. HIGH_CPU, OOM_KILL)",
    )
    severity_levels: list[IncidentSeverity] = Field(
        default_factory=lambda: [IncidentSeverity.HIGH, IncidentSeverity.CRITICAL],
        description="Applicable incident severities",
    )
    prerequisites: list[str] = Field(
        default_factory=list, description="Prerequisite conditions before executing remediation"
    )
    diagnostic_steps: list[str] = Field(
        ..., min_length=1, description="Step-by-step diagnostic triage procedures"
    )
    remediation_steps: list[str] = Field(
        ..., min_length=1, description="Ordered remediation actions to restore service"
    )
    rollback_steps: list[str] = Field(
        default_factory=list, description="Safeguard rollback actions if remediation fails"
    )
    verification_steps: list[str] = Field(
        default_factory=list, description="Verification checks to ensure stability post-remediation"
    )
    sections: list[RunbookSection] = Field(
        default_factory=list, description="Optional detailed sections"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary tags or metadata")


class RunbookCreate(RunbookBase):
    pass


class RunbookUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    service: str | None = None
    incident_types: list[str] | None = None
    severity_levels: list[IncidentSeverity] | None = None
    prerequisites: list[str] | None = None
    diagnostic_steps: list[str] | None = None
    remediation_steps: list[str] | None = None
    rollback_steps: list[str] | None = None
    verification_steps: list[str] | None = None
    sections: list[RunbookSection] | None = None
    metadata: dict[str, Any] | None = None


class Runbook(RunbookBase):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunbookSearchResult(BaseModel):
    runbook: Runbook
    score: float = Field(..., ge=0.0, le=1.0, description="Cosine similarity score")
    matched_chunk: str | None = Field(
        default=None, description="Contextual snippet that triggered the match"
    )


class RunbookSearchRequest(BaseModel):
    query: str = Field(
        ..., min_length=3, description="Incident symptom, error log, or scenario description"
    )
    service: str | None = Field(default=None, description="Optional target service filter")
    incident_type: str | None = Field(default=None, description="Optional incident type filter")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of runbooks to retrieve")
    score_threshold: float = Field(
        default=0.20, ge=0.0, le=1.0, description="Minimum cosine similarity cutoff"
    )
