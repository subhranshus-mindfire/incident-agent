from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants.enums import EvidenceType, RemediationStatus
from app.models.evidence import Evidence
from app.models.investigation import Investigation
from app.models.remediation import RemediationAction
from app.repository.base import BaseRepository


class InvestigationRepository(BaseRepository[Investigation]):
    """Repository handling investigations, collected evidence, and remediation plans."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Investigation, session)

    async def get_with_details(self, investigation_id: str) -> Investigation | None:
        """Fetch investigation with all evidence and remediation actions loaded."""
        query = (
            select(Investigation)
            .where(Investigation.id == investigation_id)
            .options(
                selectinload(Investigation.evidences),
                selectinload(Investigation.remediations),
                selectinload(Investigation.incident),
            )
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_latest_for_incident(self, incident_id: str) -> Investigation | None:
        """Fetch the latest investigation for a given incident."""
        query = (
            select(Investigation)
            .where(Investigation.incident_id == incident_id)
            .order_by(Investigation.created_at.desc())
            .options(
                selectinload(Investigation.evidences),
                selectinload(Investigation.remediations),
            )
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def add_evidence(
        self,
        investigation_id: str,
        evidence_type: EvidenceType,
        source: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> Evidence:
        """Add an immutable evidence record to an ongoing investigation."""
        evidence = Evidence(
            investigation_id=investigation_id,
            evidence_type=evidence_type,
            source=source,
            summary=summary,
            payload=payload or {},
        )
        self.session.add(evidence)
        await self.session.flush()
        await self.session.refresh(evidence)
        return evidence

    async def add_remediation_action(
        self,
        investigation_id: str,
        action_type: str,
        description: str,
        blast_radius: str = "low",
        approval_required: bool = True,
        execution_payload: dict[str, Any] | None = None,
    ) -> RemediationAction:
        """Add a proposed remediation action requiring approval."""
        action = RemediationAction(
            investigation_id=investigation_id,
            action_type=action_type,
            description=description,
            blast_radius=blast_radius,
            approval_required=approval_required,
            execution_payload=execution_payload or {},
        )
        self.session.add(action)
        await self.session.flush()
        await self.session.refresh(action)
        return action

    async def update_remediation_status(
        self,
        action_id: str,
        new_status: RemediationStatus,
        approved_by: str | None = None,
        execution_result: dict[str, Any] | None = None,
    ) -> RemediationAction | None:
        """Update remediation action lifecycle state upon approval/execution."""
        action = await self.session.get(RemediationAction, action_id)
        if not action:
            return None
        action.status = new_status
        if approved_by:
            action.approved_by = approved_by
        if execution_result:
            action.execution_result = execution_result
        await self.session.flush()
        await self.session.refresh(action)
        return action
