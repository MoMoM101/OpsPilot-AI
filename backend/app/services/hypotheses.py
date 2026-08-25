from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.hypotheses import HypothesisStatus, transition_hypothesis
from app.domain.incidents import IncidentStatus
from app.services.events import EventRecorder
from app.storage.models import HypothesisRecord
from app.storage.repositories import (
    EvidenceRepository,
    HypothesisRepository,
    IncidentRepository,
)
from app.storage.transactions import commit_session

_HYPOTHESIS_INCIDENT_STATUSES = {
    IncidentStatus.CORRELATING,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.DIAGNOSED,
    IncidentStatus.PLANNING,
    IncidentStatus.OBSERVABILITY_LOST,
    IncidentStatus.NEEDS_HUMAN,
}


class HypothesisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.hypotheses = HypothesisRepository(session)
        self.incidents = IncidentRepository(session)
        self.evidence = EvidenceRepository(session)
        self.events = EventRecorder(session)

    async def create(
        self,
        *,
        incident_id: UUID,
        summary: str,
        confidence: int,
        supporting_evidence_ids: list[UUID],
        contradicting_evidence_ids: list[UUID],
    ) -> HypothesisRecord:
        incident = await self.incidents.get(incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        if incident.status not in _HYPOTHESIS_INCIDENT_STATUSES:
            raise ApplicationError(
                "INCIDENT_NOT_INVESTIGATING",
                f"Cannot create hypotheses while incident is {incident.status.value}",
                409,
            )
        await self._validate_evidence(
            incident_id,
            supporting_evidence_ids,
            contradicting_evidence_ids,
        )
        record = await self.hypotheses.create(
            incident_id=incident_id,
            summary=summary,
            confidence=confidence,
            supporting_evidence_ids=[str(item) for item in supporting_evidence_ids],
            contradicting_evidence_ids=[str(item) for item in contradicting_evidence_ids],
        )
        occurred_at = datetime.now(UTC)
        await self.events.record(
            incident,
            "hypothesis.created",
            occurred_at,
            "agent",
            self._event_payload(record),
            aggregate_type="hypothesis",
            aggregate_id=record.id,
            aggregate_version=record.version,
        )
        await commit_session(self.session)
        return record

    async def update(
        self,
        *,
        incident_id: UUID,
        hypothesis_id: UUID,
        expected_version: int,
        summary: str | None,
        confidence: int | None,
        status: HypothesisStatus | None,
        supporting_evidence_ids: list[UUID] | None,
        contradicting_evidence_ids: list[UUID] | None,
    ) -> HypothesisRecord:
        incident = await self.incidents.get(incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        record = await self.hypotheses.get(hypothesis_id, for_update=True)
        if record is None or record.incident_id != incident_id:
            raise ApplicationError("HYPOTHESIS_NOT_FOUND", "Hypothesis does not exist", 404)
        if record.version != expected_version:
            raise ApplicationError(
                "HYPOTHESIS_VERSION_CONFLICT",
                "Hypothesis has changed; reload before retrying",
                409,
            )
        support = (
            supporting_evidence_ids
            if supporting_evidence_ids is not None
            else [UUID(item) for item in record.supporting_evidence_ids]
        )
        contradict = (
            contradicting_evidence_ids
            if contradicting_evidence_ids is not None
            else [UUID(item) for item in record.contradicting_evidence_ids]
        )
        await self._validate_evidence(incident_id, support, contradict)

        previous_status = record.status
        if summary is not None:
            record.summary = summary
        if confidence is not None:
            record.confidence = confidence
        if status is not None and status != record.status:
            try:
                record.status = transition_hypothesis(record.status, status)
            except ValueError as exc:
                raise ApplicationError("INVALID_HYPOTHESIS_TRANSITION", str(exc), 409) from exc
        if supporting_evidence_ids is not None:
            record.supporting_evidence_ids = [str(item) for item in support]
        if contradicting_evidence_ids is not None:
            record.contradicting_evidence_ids = [str(item) for item in contradict]
        record.version += 1
        record.updated_at = datetime.now(UTC)
        await self.events.record(
            incident,
            "hypothesis.updated",
            record.updated_at,
            "agent",
            {
                **self._event_payload(record),
                "previousStatus": previous_status.value,
            },
            aggregate_type="hypothesis",
            aggregate_id=record.id,
            aggregate_version=record.version,
        )
        await commit_session(self.session)
        return record

    async def list_for_incident(
        self, incident_id: UUID, limit: int, offset: int
    ) -> tuple[list[HypothesisRecord], int]:
        if await self.incidents.get(incident_id) is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        records = await self.hypotheses.list_for_incident(incident_id, limit, offset)
        total = await self.hypotheses.count_for_incident(incident_id)
        return records, total

    async def _validate_evidence(
        self,
        incident_id: UUID,
        supporting: list[UUID],
        contradicting: list[UUID],
    ) -> None:
        supporting_set = set(supporting)
        contradicting_set = set(contradicting)
        if supporting_set & contradicting_set:
            raise ApplicationError(
                "HYPOTHESIS_EVIDENCE_CONFLICT",
                "Evidence cannot both support and contradict the same hypothesis",
                422,
            )
        requested = supporting_set | contradicting_set
        existing = await self.evidence.existing_ids_for_incident(incident_id, requested)
        if existing != requested:
            raise ApplicationError(
                "HYPOTHESIS_EVIDENCE_NOT_FOUND",
                "All Evidence IDs must belong to the Incident",
                422,
            )

    @staticmethod
    def _event_payload(record: HypothesisRecord) -> dict[str, object]:
        return {
            "hypothesisId": str(record.id),
            "ordinal": record.ordinal,
            "summary": record.summary,
            "confidence": record.confidence,
            "status": record.status.value,
            "supportingEvidenceIds": record.supporting_evidence_ids,
            "contradictingEvidenceIds": record.contradicting_evidence_ids,
            "version": record.version,
        }
