from datetime import UTC, datetime

from pydantic import BaseModel, Field


class SeedHistoricalIncident(BaseModel):
    id: str
    service: str
    symptoms: str
    root_cause: str
    remediation: str
    outcome: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
