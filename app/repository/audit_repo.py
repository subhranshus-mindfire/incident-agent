from typing import List, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.repository.base import BaseRepository
from app.models.audit_log import AuditLog
from app.constants.enums import AuditAction


class AuditLogRepository(BaseRepository[AuditLog]):
    """Repository handling immutable audit trails for compliance and postmortems."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AuditLog, session)

    async def log(
        self,
        entity_type: str,
        entity_id: str,
        action: AuditAction,
        actor: str = "system",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """Create an immutable audit entry."""
        audit_entry = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            details=details or {},
        )
        self.session.add(audit_entry)
        await self.session.flush()
        await self.session.refresh(audit_entry)
        return audit_entry

    async def list_for_entity(
        self,
        entity_type: str,
        entity_id: str,
        limit: int = 50,
    ) -> List[AuditLog]:
        """Retrieve audit history for a specific entity."""
        query = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
