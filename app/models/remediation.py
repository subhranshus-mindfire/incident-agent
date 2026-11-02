from datetime import datetime
import uuid
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, JSON, Enum as SQLEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.config.database import Base
from app.constants.enums import RemediationStatus

if TYPE_CHECKING:
    from app.models.investigation import Investigation


def generate_uuid() -> str:
    return f"rem-{uuid.uuid4().hex[:12]}"


class RemediationAction(Base):
    __tablename__ = "remediation_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    investigation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    blast_radius: Mapped[str] = mapped_column(String(32), default="low", nullable=False)
    status: Mapped[RemediationStatus] = mapped_column(
        SQLEnum(RemediationStatus, name="remediation_status_enum", native_enum=False),
        default=RemediationStatus.PENDING_APPROVAL,
        nullable=False,
        index=True,
    )
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    execution_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    execution_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    investigation: Mapped["Investigation"] = relationship("Investigation", back_populates="remediations")
