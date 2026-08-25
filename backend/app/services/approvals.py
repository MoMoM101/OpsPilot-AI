from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.core.principal_context import principal_context
from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.domain.investigations import InvestigationHITLSubjectType
from app.services.action_proposals import ActionProposalService
from app.services.events import EventRecorder
from app.services.investigation_hitl import InvestigationHITLService
from app.services.policies import PolicyService
from app.storage.models import ApprovalRecord
from app.storage.repositories import (
    ApprovalRepository,
    IncidentRepository,
    PolicyRepository,
)
from app.storage.transactions import commit_session


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.approvals = ApprovalRepository(session)
        self.policies = PolicyRepository(session)
        self.incidents = IncidentRepository(session)
        self.events = EventRecorder(session)

    async def create(
        self,
        *,
        policy_decision_id: UUID,
        parameters: Mapping[str, object],
        editable_parameter_keys: list[str],
        expires_in_seconds: int,
        commit: bool = True,
    ) -> ApprovalRecord:
        snapshot = await self.policies.get_decision(policy_decision_id)
        if snapshot is None:
            raise ApplicationError(
                "POLICY_DECISION_NOT_FOUND", "Policy Decision Snapshot does not exist", 404
            )
        if not snapshot.allowed or not snapshot.approval_required:
            raise ApplicationError(
                "APPROVAL_NOT_REQUIRED",
                "Only an allowed Policy decision requiring approval can create an Approval",
                409,
            )
        incident = await self.incidents.get(snapshot.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        actor = principal_context.get()
        now = datetime.now(UTC)
        try:
            record = await self.approvals.create(
                policy_decision_id=snapshot.id,
                environment_id=snapshot.environment_id,
                incident_id=snapshot.incident_id,
                resource_id=snapshot.resource_id,
                capability=snapshot.capability,
                status=ApprovalStatus.PENDING,
                requested_by=actor.actor_id if actor else "system",
                expires_at=now + timedelta(seconds=expires_in_seconds),
                parameters=dict(parameters),
                editable_parameter_keys=editable_parameter_keys,
            )
            await self.events.record(
                incident,
                "approval.requested",
                now,
                "user" if actor else "system",
                {
                    "approvalId": str(record.id),
                    "policyDecisionId": str(snapshot.id),
                    "capability": snapshot.capability,
                    "expiresAt": record.expires_at.isoformat(),
                },
                aggregate_type="approval",
                aggregate_id=record.id,
                aggregate_version=record.version,
            )
            if commit:
                await commit_session(self.session)
        except IntegrityError as exc:
            raise ApplicationError(
                "APPROVAL_ALREADY_EXISTS",
                "An Approval already exists for this Policy Decision Snapshot",
                409,
            ) from exc
        return record

    async def decide(
        self,
        approval_id: UUID,
        *,
        decision: ApprovalDecision,
        expected_version: int,
        comment: str | None,
        parameter_edits: Mapping[str, object],
    ) -> ApprovalRecord:
        record = await self.approvals.get(approval_id, for_update=True)
        if record is None:
            raise ApplicationError("APPROVAL_NOT_FOUND", "Approval does not exist", 404)
        if record.version != expected_version:
            raise ApplicationError(
                "APPROVAL_VERSION_CONFLICT",
                "Approval has changed; reload before retrying",
                409,
            )
        if record.status != ApprovalStatus.PENDING:
            raise ApplicationError(
                "APPROVAL_ALREADY_RESOLVED", "Approval is no longer pending", 409
            )
        now = datetime.now(UTC)
        if self._as_utc(record.expires_at) <= now:
            await self._resolve(record, ApprovalStatus.EXPIRED, now, "Approval expired")
            await ActionProposalService(self.session).resolve_approval(record, now)
            await InvestigationHITLService(self.session).resolve_subject(
                InvestigationHITLSubjectType.APPROVAL,
                record.id,
                ApprovalStatus.EXPIRED.value,
                now,
            )
            await commit_session(self.session)
            return record
        actor = principal_context.get()
        if actor is not None and record.requested_by == actor.actor_id:
            raise ApplicationError(
                "APPROVAL_SELF_DECISION_FORBIDDEN",
                "The Approval requester cannot decide the same Approval",
                403,
            )
        invalid_keys = set(parameter_edits) - set(record.editable_parameter_keys)
        if invalid_keys:
            raise ApplicationError(
                "APPROVAL_PARAMETER_EDIT_FORBIDDEN",
                "Only explicitly editable Approval parameters may be changed",
                422,
            )
        if decision == ApprovalDecision.APPROVE:
            snapshot = await self.policies.get_decision(record.policy_decision_id)
            if snapshot is None:
                raise ApplicationError(
                    "POLICY_DECISION_NOT_FOUND",
                    "Policy Decision Snapshot does not exist",
                    409,
                )
            current = await PolicyService(self.session).revalidate_snapshot(snapshot)
            if not current.allowed or not current.approval_required:
                raise ApplicationError(
                    "POLICY_REVALIDATION_FAILED",
                    f"Approval cannot be granted: {current.reason}",
                    409,
                )
        record.parameters = {**record.parameters, **parameter_edits}
        target = (
            ApprovalStatus.APPROVED
            if decision == ApprovalDecision.APPROVE
            else ApprovalStatus.REJECTED
        )
        await self._resolve(record, target, now, comment)
        await ActionProposalService(self.session).resolve_approval(record, now)
        await InvestigationHITLService(self.session).resolve_subject(
            InvestigationHITLSubjectType.APPROVAL,
            record.id,
            target.value,
            now,
        )
        await commit_session(self.session)
        return record

    async def list(
        self,
        *,
        incident_id: UUID | None,
        status: ApprovalStatus | None,
        limit: int,
        offset: int,
    ) -> list[ApprovalRecord]:
        return await self.approvals.list(
            incident_id=incident_id, status=status, limit=limit, offset=offset
        )

    async def count(
        self, *, incident_id: UUID | None, status: ApprovalStatus | None
    ) -> int:
        return await self.approvals.count(incident_id=incident_id, status=status)

    async def _resolve(
        self,
        record: ApprovalRecord,
        status: ApprovalStatus,
        now: datetime,
        comment: str | None,
    ) -> None:
        actor = principal_context.get()
        record.status = status
        record.decided_by = actor.actor_id if actor else "system"
        record.decided_at = now
        record.decision_comment = comment
        record.version += 1
        record.updated_at = now
        incident = await self.incidents.get(record.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        await self.events.record(
            incident,
            "approval.resolved",
            now,
            "user" if actor else "system",
            {"approvalId": str(record.id), "status": status.value},
            aggregate_type="approval",
            aggregate_id=record.id,
            aggregate_version=record.version,
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
