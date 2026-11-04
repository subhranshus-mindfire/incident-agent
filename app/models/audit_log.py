from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base
from app.constants.enums import AuditAction
from app.utils.ids import new_id


def generate_uuid() -> str:
    return new_id("aud")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[AuditAction] = mapped_column(
        SQLEnum(AuditAction, name="audit_action_enum", native_enum=False),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
