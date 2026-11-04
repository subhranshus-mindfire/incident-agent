from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base
from app.constants.enums import InvestigationStatus
from app.utils.ids import new_id

if TYPE_CHECKING:
    from app.models.evidence import Evidence
    from app.models.incident import Incident
    from app.models.remediation import RemediationAction


def generate_uuid() -> str:
    return new_id("inv")


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    incident_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[InvestigationStatus] = mapped_column(
        SQLEnum(InvestigationStatus, name="investigation_status_enum", native_enum=False),
        default=InvestigationStatus.PENDING,
        nullable=False,
        index=True,
    )
    root_cause_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
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

    # Relationships
    incident: Mapped["Incident"] = relationship("Incident", back_populates="investigations")
    evidences: Mapped[list["Evidence"]] = relationship(
        "Evidence",
        back_populates="investigation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    remediations: Mapped[list["RemediationAction"]] = relationship(
        "RemediationAction",
        back_populates="investigation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
