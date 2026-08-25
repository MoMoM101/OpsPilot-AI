from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.actions import CompensationStatus
from app.domain.approvals import ApprovalStatus
from app.domain.investigations import (
    InvestigationHITLSubjectType,
    InvestigationHITLWaitStatus,
    InvestigationRunStatus,
)
from app.services.events import EventRecorder
from app.storage.models import InvestigationHITLWaitRecord
from app.storage.repositories import (
    ApprovalRepository,
    CompensationRepository,
    IncidentRepository,
    InvestigationRepository,
)
from app.storage.transactions import commit_session


class InvestigationHITLService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.runs = InvestigationRepository(session)
        self.approvals = ApprovalRepository(session)
        self.compensations = CompensationRepository(session)
        self.incidents = IncidentRepository(session)
        self.events = EventRecorder(session)

    async def start_wait(
        self,
        *,
        run_id: UUID,
        checkpoint_id: UUID,
        subject_type: InvestigationHITLSubjectType,
        subject_id: UUID,
        expected_run_version: int,
    ) -> tuple[InvestigationHITLWaitRecord, bool]:
        existing = await self.runs.get_hitl_wait(run_id, subject_type, subject_id)
        if existing is not None:
            if existing.checkpoint_id != checkpoint_id:
                raise ApplicationError(
                    "INVESTIGATION_HITL_WAIT_CONFLICT",
                    "The HITL subject is already attached to another checkpoint",
                    409,
                )
            return existing, True

        run = await self.runs.get_run(run_id, for_update=True)
        if run is None:
            raise ApplicationError(
                "INVESTIGATION_RUN_NOT_FOUND", "Investigation run does not exist", 404
            )
        if run.version != expected_run_version:
            raise ApplicationError(
                "INVESTIGATION_RUN_VERSION_CONFLICT",
                "Investigation run has changed; reload before retrying",
                409,
            )
        if run.status != InvestigationRunStatus.RUNNING:
            raise ApplicationError(
                "INVESTIGATION_RUN_NOT_RUNNING",
                "A HITL wait can only interrupt a running investigation",
                409,
            )
        checkpoint = await self.runs.get_checkpoint(checkpoint_id)
        if checkpoint is None or checkpoint.run_id != run.id:
            raise ApplicationError(
                "INVESTIGATION_CHECKPOINT_NOT_FOUND",
                "HITL wait checkpoint must belong to the investigation run",
                422,
            )
        await self._validate_pending_subject(subject_type, subject_id, run.incident_id)
        incident = await self.incidents.get(run.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)

        now = datetime.now(UTC)
        wait = await self.runs.create_hitl_wait(
            run_id=run.id,
            incident_id=run.incident_id,
            checkpoint_id=checkpoint.id,
            subject_type=subject_type,
            subject_id=subject_id,
            status=InvestigationHITLWaitStatus.WAITING,
            version=1,
        )
        run.status = InvestigationRunStatus.PAUSED
        run.runtime_owner = None
        run.runtime_lease_expires_at = None
        run.version += 1
        run.updated_at = now
        await self.events.record(
            incident,
            "investigation.hitl_wait_started",
            now,
            "agent_runtime",
            {
                "runId": str(run.id),
                "waitId": str(wait.id),
                "checkpointId": str(checkpoint.id),
                "subjectType": subject_type.value,
                "subjectId": str(subject_id),
                "version": run.version,
            },
            aggregate_type="investigation_run",
            aggregate_id=run.id,
            aggregate_version=run.version,
        )
        await commit_session(self.session)
        return wait, False

    async def resolve_subject(
        self,
        subject_type: InvestigationHITLSubjectType,
        subject_id: UUID,
        outcome: str,
        now: datetime,
    ) -> InvestigationHITLWaitRecord | None:
        wait = await self.runs.get_waiting_hitl_for_subject(subject_type, subject_id)
        if wait is None:
            return None
        run = await self.runs.get_run(wait.run_id, for_update=True)
        if run is None:
            raise ApplicationError(
                "INVESTIGATION_RUN_NOT_FOUND", "Investigation run does not exist", 404
            )
        incident = await self.incidents.get(wait.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)

        wait.status = InvestigationHITLWaitStatus.RESOLVED
        wait.outcome = outcome
        wait.resolved_at = now
        wait.version += 1
        wait.updated_at = now
        if run.status == InvestigationRunStatus.PAUSED:
            run.status = InvestigationRunStatus.QUEUED
            run.runtime_owner = None
            run.runtime_lease_expires_at = None
            run.last_error_code = None
            run.version += 1
            run.updated_at = now
        await self.events.record(
            incident,
            "investigation.hitl_wait_resolved",
            now,
            "user",
            {
                "runId": str(run.id),
                "waitId": str(wait.id),
                "subjectType": subject_type.value,
                "subjectId": str(subject_id),
                "outcome": outcome,
                "runStatus": run.status.value,
                "version": run.version,
            },
            aggregate_type="investigation_run",
            aggregate_id=run.id,
            aggregate_version=run.version,
        )
        return wait

    async def list_waits(
        self, run_id: UUID, limit: int, offset: int
    ) -> tuple[list[InvestigationHITLWaitRecord], int]:
        if await self.runs.get_run(run_id) is None:
            raise ApplicationError(
                "INVESTIGATION_RUN_NOT_FOUND", "Investigation run does not exist", 404
            )
        waits = await self.runs.list_hitl_waits(run_id, limit, offset)
        total = await self.runs.count_hitl_waits(run_id)
        return waits, total

    async def _validate_pending_subject(
        self,
        subject_type: InvestigationHITLSubjectType,
        subject_id: UUID,
        incident_id: UUID,
    ) -> None:
        if subject_type == InvestigationHITLSubjectType.APPROVAL:
            approval = await self.approvals.get(subject_id)
            valid = approval is not None and approval.status == ApprovalStatus.PENDING
            subject_incident_id = approval.incident_id if approval is not None else None
        else:
            compensation = await self.compensations.get(subject_id)
            valid = compensation is not None and compensation.status == CompensationStatus.PENDING
            subject_incident_id = compensation.incident_id if compensation is not None else None
        if not valid:
            raise ApplicationError(
                "INVESTIGATION_HITL_SUBJECT_NOT_PENDING",
                "HITL subject must exist and be pending",
                409,
            )
        if subject_incident_id != incident_id:
            raise ApplicationError(
                "INVESTIGATION_HITL_INCIDENT_MISMATCH",
                "HITL subject must belong to the investigation Incident",
                422,
            )
