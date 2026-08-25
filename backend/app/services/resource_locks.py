from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.core.principal_context import principal_context
from app.domain.actions import ActionRequestStatus
from app.domain.approvals import ApprovalStatus
from app.services.events import EventRecorder
from app.services.policies import PolicyService
from app.storage.models import ResourceLockRecord
from app.storage.repositories import (
    ActionRequestRepository,
    ApprovalRepository,
    IncidentRepository,
    PolicyRepository,
    ResourceLockRepository,
)
from app.storage.transactions import commit_session


class ResourceLockService:
    def __init__(self, session: AsyncSession, lease_seconds: int) -> None:
        self.session = session
        self.lease_duration = timedelta(seconds=lease_seconds)
        self.actions = ActionRequestRepository(session)
        self.approvals = ApprovalRepository(session)
        self.locks = ResourceLockRepository(session)
        self.incidents = IncidentRepository(session)
        self.policies = PolicyRepository(session)
        self.events = EventRecorder(session)

    async def acquire(
        self, action_id: UUID, *, commit: bool = True
    ) -> tuple[ResourceLockRecord, bool]:
        action = await self.actions.get(action_id, for_update=True)
        if action is None:
            raise ApplicationError("ACTION_NOT_FOUND", "Action Request does not exist", 404)
        if action.status != ActionRequestStatus.READY:
            raise ApplicationError(
                "ACTION_NOT_LOCKABLE", "Only a ready Action Request can acquire a lock", 409
            )
        await self._revalidate_authorization(
            action.policy_decision_id, action.approval_id, action.parameters
        )
        now = datetime.now(UTC)
        expires_at = now + self.lease_duration
        lock = await self.locks.get_for_resource(action.resource_id, for_update=True)
        created = False
        if lock is None:
            if not commit:
                try:
                    lock = await self.locks.create(
                        environment_id=action.environment_id,
                        resource_id=action.resource_id,
                        action_request_id=action.id,
                        incident_id=action.incident_id,
                        fencing_token=1,
                        acquired_at=now,
                        renewed_at=now,
                        expires_at=expires_at,
                    )
                    created = True
                except IntegrityError as exc:
                    raise ApplicationError(
                        "RESOURCE_LOCK_CONFLICT",
                        "Resource is being locked by another Action Request",
                        409,
                    ) from exc
            else:
                try:
                    async with self.session.begin_nested():
                        lock = await self.locks.create(
                            environment_id=action.environment_id,
                            resource_id=action.resource_id,
                            action_request_id=action.id,
                            incident_id=action.incident_id,
                            fencing_token=1,
                            acquired_at=now,
                            renewed_at=now,
                            expires_at=expires_at,
                        )
                        created = True
                except IntegrityError:
                    lock = await self.locks.get_for_resource(action.resource_id, for_update=True)
                    if lock is None:
                        raise
        if created:
            await self._event(action.id, lock, "resource_lock.acquired", now)
            if commit:
                await commit_session(self.session)
            return lock, False
        if (
            lock.action_request_id == action.id
            and lock.released_at is None
            and self._as_utc(lock.expires_at) > now
        ):
            return lock, True
        if lock.reconciliation_required:
            raise ApplicationError(
                "RESOURCE_LOCK_RECONCILIATION_REQUIRED",
                "Resource is frozen until the unknown Action is reconciled",
                409,
            )
        if lock.released_at is None and self._as_utc(lock.expires_at) > now:
            raise ApplicationError(
                "RESOURCE_LOCK_CONFLICT",
                "Resource is locked by another Action Request",
                409,
            )
        lock.action_request_id = action.id
        lock.incident_id = action.incident_id
        lock.environment_id = action.environment_id
        lock.fencing_token += 1
        lock.acquired_at = now
        lock.renewed_at = now
        lock.expires_at = expires_at
        lock.released_at = None
        lock.released_by = None
        lock.updated_at = now
        await self._event(action.id, lock, "resource_lock.acquired", now)
        if commit:
            await commit_session(self.session)
        return lock, False

    async def _revalidate_authorization(
        self,
        snapshot_id: UUID,
        approval_id: UUID | None,
        parameters: Mapping[str, object],
    ) -> None:
        snapshot = await self.policies.get_decision(snapshot_id)
        if snapshot is None:
            raise ApplicationError(
                "POLICY_DECISION_NOT_FOUND", "Policy Decision Snapshot does not exist", 409
            )
        current = await PolicyService(self.session).revalidate_snapshot(snapshot)
        if not current.allowed or current.approval_required != snapshot.approval_required:
            raise ApplicationError(
                "POLICY_REVALIDATION_FAILED",
                f"Resource lock cannot be acquired: {current.reason}",
                409,
            )
        if not snapshot.approval_required:
            return
        if approval_id is None:
            raise ApplicationError(
                "ACTION_APPROVAL_REQUIRED", "An approved Approval is required", 409
            )
        approval = await self.approvals.get(approval_id)
        now = datetime.now(UTC)
        if (
            approval is None
            or approval.policy_decision_id != snapshot.id
            or approval.status != ApprovalStatus.APPROVED
            or self._as_utc(approval.expires_at) <= now
        ):
            raise ApplicationError(
                "ACTION_APPROVAL_INVALID",
                "Approval is missing, expired, or no longer approved",
                409,
            )
        if approval.parameters != parameters:
            raise ApplicationError(
                "ACTION_PARAMETERS_CHANGED",
                "Action parameters no longer match the approved parameters",
                409,
            )

    async def renew(self, action_id: UUID, fencing_token: int) -> ResourceLockRecord:
        lock = await self._owned_active(action_id, fencing_token)
        now = datetime.now(UTC)
        lock.renewed_at = now
        lock.expires_at = now + self.lease_duration
        lock.updated_at = now
        await commit_session(self.session)
        return lock

    async def release(self, action_id: UUID, fencing_token: int) -> ResourceLockRecord:
        lock = await self._owned_active(action_id, fencing_token)
        now = datetime.now(UTC)
        actor = principal_context.get()
        lock.released_at = now
        lock.released_by = actor.actor_id if actor else "system"
        lock.expires_at = now
        lock.updated_at = now
        await self._event(
            action_id=action_id,
            lock=lock,
            event_type="resource_lock.released",
            now=now,
        )
        await commit_session(self.session)
        return lock

    async def _owned_active(self, action_id: UUID, fencing_token: int) -> ResourceLockRecord:
        action = await self.actions.get(action_id, for_update=True)
        if action is None:
            raise ApplicationError("ACTION_NOT_FOUND", "Action Request does not exist", 404)
        if action.status != ActionRequestStatus.READY:
            raise ApplicationError(
                "RESOURCE_LOCK_MANUAL_CHANGE_FORBIDDEN",
                "A lock owned by an executing or completed Action cannot be manually changed",
                409,
            )
        lock = await self.locks.get_for_action(action_id, for_update=True)
        if lock is None:
            raise ApplicationError("RESOURCE_LOCK_NOT_FOUND", "Resource lock does not exist", 404)
        if lock.fencing_token != fencing_token:
            raise ApplicationError(
                "RESOURCE_LOCK_FENCED", "Resource lock Fencing Token is stale", 409
            )
        now = datetime.now(UTC)
        if lock.released_at is not None or self._as_utc(lock.expires_at) <= now:
            raise ApplicationError("RESOURCE_LOCK_EXPIRED", "Resource lock has expired", 409)
        return lock

    async def _event(
        self,
        action_id: UUID,
        lock: ResourceLockRecord,
        event_type: str,
        now: datetime,
    ) -> None:
        incident = await self.incidents.get(lock.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        await self.events.record(
            incident,
            event_type,
            now,
            "user",
            {
                "actionId": str(action_id),
                "resourceId": str(lock.resource_id),
                "expiresAt": lock.expires_at.isoformat(),
            },
            aggregate_type="resource_lock",
            aggregate_id=lock.id,
            aggregate_version=lock.fencing_token,
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
