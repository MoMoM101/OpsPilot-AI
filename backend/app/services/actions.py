import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.core.principal_context import principal_context
from app.domain.actions import ActionRequestStatus
from app.domain.approvals import ApprovalStatus
from app.services.action_capabilities import action_capability_definition
from app.services.events import EventRecorder
from app.services.policies import PolicyService
from app.storage.models import ActionRequestRecord
from app.storage.repositories import (
    ActionRequestRepository,
    ApprovalRepository,
    IncidentRepository,
    PolicyRepository,
    ResourceLockRepository,
)
from app.storage.transactions import commit_session


class ActionRequestService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.actions = ActionRequestRepository(session)
        self.approvals = ApprovalRepository(session)
        self.policies = PolicyRepository(session)
        self.incidents = IncidentRepository(session)
        self.events = EventRecorder(session)
        self.locks = ResourceLockRepository(session)

    async def create(
        self,
        *,
        policy_decision_id: UUID,
        approval_id: UUID | None,
        parameters: Mapping[str, object],
        verification_criteria: Sequence[str],
        rollback_capability: str | None,
        idempotency_key: str,
        commit: bool = True,
    ) -> tuple[ActionRequestRecord, bool]:
        snapshot = await self.policies.get_decision(policy_decision_id, for_update=True)
        if snapshot is None:
            raise ApplicationError(
                "POLICY_DECISION_NOT_FOUND", "Policy Decision Snapshot does not exist", 404
            )
        if not snapshot.allowed:
            raise ApplicationError(
                "ACTION_POLICY_DENIED",
                "A denied Policy Decision cannot create an Action Request",
                409,
            )
        self._validate_capability_parameters(snapshot.capability, parameters)
        self.validate_rollback_capability(snapshot.capability, rollback_capability)
        normalized_parameters = dict(parameters)
        fingerprint = self._fingerprint(
            policy_decision_id,
            approval_id,
            normalized_parameters,
            verification_criteria,
            rollback_capability,
        )
        existing = await self.actions.get_by_idempotency_key(
            snapshot.environment_id, idempotency_key
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ApplicationError(
                    "ACTION_IDEMPOTENCY_CONFLICT",
                    "Idempotency key already belongs to a different Action Request",
                    409,
                )
            return existing, True
        consumed = await self.actions.get_by_policy_decision(snapshot.id)
        if consumed is not None:
            raise ApplicationError(
                "ACTION_AUTHORIZATION_ALREADY_CONSUMED",
                "Policy Decision authorization has already created an Action Request",
                409,
            )
        await self._validate_approval(
            snapshot.id,
            snapshot.approval_required,
            approval_id,
            normalized_parameters,
        )
        current = await PolicyService(self.session).authorize_action_creation(snapshot)
        if not current.allowed or current.approval_required != snapshot.approval_required:
            raise ApplicationError(
                "POLICY_REVALIDATION_FAILED",
                f"Action Request cannot be created: {current.reason}",
                409,
            )
        incident = await self.incidents.get(snapshot.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        actor = principal_context.get()
        now = datetime.now(UTC)
        try:
            async with self.session.begin_nested():
                record = await self.actions.create(
                    policy_decision_id=snapshot.id,
                    approval_id=approval_id,
                    environment_id=snapshot.environment_id,
                    incident_id=snapshot.incident_id,
                    resource_id=snapshot.resource_id,
                    capability=snapshot.capability,
                    status=ActionRequestStatus.READY,
                    parameters=normalized_parameters,
                    verification_criteria=list(verification_criteria),
                    rollback_capability=rollback_capability,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                    created_by=actor.actor_id if actor else "system",
                )
        except IntegrityError as exc:
            raced = await self.actions.get_by_idempotency_key(
                snapshot.environment_id, idempotency_key
            )
            if raced is not None and raced.request_fingerprint == fingerprint:
                return raced, True
            raise ApplicationError(
                "ACTION_AUTHORIZATION_ALREADY_CONSUMED",
                "Policy Decision or Approval authorization has already been consumed",
                409,
            ) from exc
        await self.events.record(
            incident,
            "action.requested",
            now,
            "user" if actor else "system",
            {
                "actionId": str(record.id),
                "approvalId": str(approval_id) if approval_id else None,
                "capability": record.capability,
                "status": record.status.value,
            },
            aggregate_type="action_request",
            aggregate_id=record.id,
            aggregate_version=record.version,
        )
        if commit:
            await commit_session(self.session)
        return record, False

    async def cancel(
        self, action_id: UUID, *, expected_version: int, reason: str
    ) -> ActionRequestRecord:
        record = await self.actions.get(action_id, for_update=True)
        if record is None:
            raise ApplicationError("ACTION_NOT_FOUND", "Action Request does not exist", 404)
        if record.version != expected_version:
            raise ApplicationError(
                "ACTION_VERSION_CONFLICT",
                "Action Request has changed; reload before retrying",
                409,
            )
        if record.status != ActionRequestStatus.READY:
            raise ApplicationError(
                "ACTION_NOT_CANCELLABLE",
                "Only a ready Action Request can be cancelled",
                409,
            )
        incident = await self.incidents.get(record.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        actor = principal_context.get()
        now = datetime.now(UTC)
        record.status = ActionRequestStatus.CANCELLED
        record.cancelled_by = actor.actor_id if actor else "system"
        record.cancellation_reason = reason
        record.version += 1
        record.updated_at = now
        released_lock = await self.locks.release_for_action(
            record.id,
            released_at=now,
            released_by=actor.actor_id if actor else "system",
        )
        await self.events.record(
            incident,
            "action.cancelled",
            now,
            "user" if actor else "system",
            {"actionId": str(record.id), "reason": reason},
            aggregate_type="action_request",
            aggregate_id=record.id,
            aggregate_version=record.version,
        )
        if released_lock is not None:
            await self.events.record(
                incident,
                "resource_lock.released",
                now,
                "user" if actor else "system",
                {
                    "actionId": str(record.id),
                    "resourceId": str(released_lock.resource_id),
                    "reason": "action.cancelled",
                },
                aggregate_type="resource_lock",
                aggregate_id=released_lock.id,
                aggregate_version=released_lock.fencing_token,
            )
        await commit_session(self.session)
        return record

    async def _validate_approval(
        self,
        snapshot_id: UUID,
        approval_required: bool,
        approval_id: UUID | None,
        parameters: dict[str, object],
    ) -> None:
        if not approval_required:
            if approval_id is not None:
                raise ApplicationError(
                    "ACTION_APPROVAL_UNEXPECTED",
                    "Policy does not require an Approval for this Action",
                    422,
                )
            return
        if approval_id is None:
            raise ApplicationError(
                "ACTION_APPROVAL_REQUIRED", "An approved Approval is required", 409
            )
        approval = await self.approvals.get(approval_id, for_update=True)
        if approval is None or approval.policy_decision_id != snapshot_id:
            raise ApplicationError(
                "ACTION_APPROVAL_INVALID",
                "Approval does not belong to this Policy Decision Snapshot",
                422,
            )
        if approval.status != ApprovalStatus.APPROVED:
            raise ApplicationError("ACTION_APPROVAL_NOT_APPROVED", "Approval is not approved", 409)
        if self._as_utc(approval.expires_at) <= datetime.now(UTC):
            raise ApplicationError("ACTION_APPROVAL_EXPIRED", "Approval validity has expired", 409)
        if approval.parameters != parameters:
            raise ApplicationError(
                "ACTION_PARAMETERS_CHANGED",
                "Action parameters must exactly match the approved parameters",
                422,
            )
        if await self.actions.get_by_approval(approval.id) is not None:
            raise ApplicationError(
                "ACTION_APPROVAL_ALREADY_CONSUMED",
                "Approval authorization has already created an Action Request",
                409,
            )

    @staticmethod
    def validate_capability_parameters(capability: str, parameters: Mapping[str, object]) -> None:
        definition = action_capability_definition(capability)
        if definition is None or definition.availability != "available":
            raise ApplicationError(
                "ACTION_CAPABILITY_UNSUPPORTED",
                "Capability has no available server execution and verification mapping",
                422,
            )

        required = definition.parameter_key
        if set(parameters) != {required}:
            raise ApplicationError(
                "ACTION_PARAMETERS_INVALID",
                f"{capability} requires only the '{required}' parameter",
                422,
            )

        value = parameters[required]
        if not isinstance(value, str) or not value.strip() or len(value) > 300:
            raise ApplicationError(
                "ACTION_PARAMETERS_INVALID",
                f"'{required}' must contain 1 to 300 characters",
                422,
            )

    _validate_capability_parameters = validate_capability_parameters

    @staticmethod
    def validate_rollback_capability(
        capability: str, rollback_capability: str | None
    ) -> None:
        if rollback_capability is None:
            return
        definition = action_capability_definition(capability)
        message = (
            f"{capability} has no deterministic rollback operation"
            if definition is not None
            else "Capability has no registered compensation operation"
        )
        raise ApplicationError(
            "ACTION_ROLLBACK_CAPABILITY_UNSUPPORTED",
            message,
            422,
        )

    @staticmethod
    def _fingerprint(
        snapshot_id: UUID,
        approval_id: UUID | None,
        parameters: Mapping[str, object],
        verification_criteria: Sequence[str],
        rollback_capability: str | None,
    ) -> str:
        payload = {
            "snapshotId": str(snapshot_id),
            "approvalId": str(approval_id) if approval_id else None,
            "parameters": parameters,
            "verificationCriteria": list(verification_criteria),
            "rollbackCapability": rollback_capability,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
