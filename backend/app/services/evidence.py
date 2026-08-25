from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.storage.models import EvidenceRecord
from app.storage.repositories import EvidenceRepository, IncidentRepository


class EvidenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.evidence = EvidenceRepository(session)
        self.incidents = IncidentRepository(session)

    async def get(self, evidence_id: UUID) -> EvidenceRecord:
        record = await self.evidence.get(evidence_id)
        if record is None:
            raise ApplicationError("EVIDENCE_NOT_FOUND", "Evidence does not exist", 404)
        return record

    async def list_for_incident(
        self,
        incident_id: UUID,
        limit: int,
        offset: int,
        evidence_type: str | None,
        resource_id: UUID | None,
    ) -> tuple[list[EvidenceRecord], int]:
        if await self.incidents.get(incident_id) is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        records = await self.evidence.list_for_incident(
            incident_id, limit, offset, evidence_type, resource_id
        )
        total = await self.evidence.count_for_incident(
            incident_id, evidence_type, resource_id
        )
        return records, total
