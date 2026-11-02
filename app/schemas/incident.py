from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class IncidentBase(BaseModel):
    title: str = Field(..., examples=["High CPU Spike in Payment Service"])
    service: str = Field(..., examples=["payment-service"])
    severity: str = Field(default="critical", examples=["critical"])
    description: Optional[str] = Field(None, examples=["CPU utilization exceeded 95% threshold"])


class IncidentCreate(IncidentBase):
    pass


class IncidentResponse(IncidentBase):
    id: str
    status: str = "open"
    created_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
