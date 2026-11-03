"""Service dependency map: which services a service depends on and which depend on it."""

from pydantic import BaseModel, Field


class ServiceDependencyMap(BaseModel):
    service: str
    upstream_services: list[str] = Field(
        default_factory=list, description="Services that depend on this service"
    )
    downstream_services: list[str] = Field(
        default_factory=list, description="Services this service depends on"
    )
    tier: str = "tier-1"
    criticality: str = "critical"
