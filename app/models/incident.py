from datetime import datetime, timezone
import uuid
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, DateTime, JSON, Enum as SQLEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.config.database import Base
from app.constants.enums import IncidentSeverity, IncidentStatus

if TYPE_CHECKING:
    from app.models.investigation import Investigation


def generate_uuid() -> str:
    return f"inc-{uuid.uuid4().hex[:12]}"


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity: Mapped[IncidentSeverity] = mapped_column(
        SQLEnum(IncidentSeverity, name="incident_severity_enum", native_enum=False),
        default=IncidentSeverity.MEDIUM,
        nullable=False,
        index=True,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        SQLEnum(IncidentStatus, name="incident_status_enum", native_enum=False),
        default=IncidentStatus.OPEN,
        nullable=False,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Relationships
    investigations: Mapped[List["Investigation"]] = relationship(
        "Investigation",
        back_populates="incident",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
