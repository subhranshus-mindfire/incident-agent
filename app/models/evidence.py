from datetime import datetime
import uuid
from typing import Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, Enum as SQLEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.config.database import Base
from app.constants.enums import EvidenceType

if TYPE_CHECKING:
    from app.models.investigation import Investigation


def generate_uuid() -> str:
    return f"evi-{uuid.uuid4().hex[:12]}"


class Evidence(Base):
    __tablename__ = "evidences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    investigation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        SQLEnum(EvidenceType, name="evidence_type_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    investigation: Mapped["Investigation"] = relationship("Investigation", back_populates="evidences")
