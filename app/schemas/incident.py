from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.constants.enums import IncidentSeverity, IncidentStatus


class IncidentBase(BaseModel):
    title: str = Field(
        ..., min_length=3, max_length=255, examples=["High CPU Spike in Payment Service"]
    )
    service: str = Field(..., min_length=2, max_length=128, examples=["payment-service"])
    severity: IncidentSeverity = Field(
        default=IncidentSeverity.MEDIUM, examples=[IncidentSeverity.CRITICAL]
    )
    description: str | None = Field(None, examples=["CPU utilization exceeded 95% threshold"])
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentCreate(IncidentBase):
    pass


class IncidentUpdateStatus(BaseModel):
    status: IncidentStatus = Field(..., examples=[IncidentStatus.INVESTIGATING])
    reason: str | None = Field(None, examples=["Investigation initiated by agent"])


class IncidentResponse(IncidentBase):
    id: str
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
