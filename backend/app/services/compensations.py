import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.core.principal_context import principal_context
from app.domain.actions import ActionRequestStatus, CompensationStatus
from app.domain.investigations import InvestigationHITLSubjectType
from app.services.events import EventRecorder
from app.services.investigation_hitl import InvestigationHITLService
from app.services.policies import PolicyService
from app.services.runners import RunnerService
from app.storage.models import (
    CompensationExecutionRecord,
    CompensationRequestRecord,
    ResourceLockRecord,
    RunnerRecord,
)
from app.storage.repositories import (
    ActionRequestRepository,
    ActionVerificationRepository,
    CompensationExecutionRepository,
    CompensationRepository,
    IncidentRepository,
    PolicyRepository,
    ResourceLockRepository,
    RunnerRepository,
)
from app.storage.transactions import commit_session


class CompensationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        execution_lease_seconds: int,
        resource_lock_lease_seconds: int,
        runner_lease_seconds: int,
        runner_token_rotation_seconds: int,
        runner_token_ttl_seconds: int,
        runner_token_grace_seconds: int,
    ) -> None:
        self.session = session
        self.execution_lease = timedelta(seconds=execution_lease_seconds)
        self.resource_lock_lease = timedelta(seconds=resource_lock_lease_seconds)
        self.compensations = CompensationRepository(session)
        self.executions = CompensationExecutionRepository(session)
        self.actions = ActionRequestRepository(session)
        self.verifications = ActionVerificationRepository(session)
        self.locks = ResourceLockRepository(session)
        self.runners = RunnerRepository(session)
        self.policies = PolicyRepository(session)
        self.incidents = IncidentRepository(session)
        self.events = EventRecorder(session)
        self.runner_service = RunnerService(
            session,
            runner_lease_seconds,
            token_rotation_seconds=runner_token_rotation_seconds,
            token_ttl_seconds=runner_token_ttl_seconds,
            token_grace_seconds=runner_token_grace_seconds,
        )

    async def create(
        self,
        action_id: UUID,
        *,
        parameters: dict[str, object],
        idempotency_key: str,
        expires_in_seconds: int,
    ) -> tuple[CompensationRequestRecord, bool]:
        action = await self.actions.get(action_id, for_update=True)
        if action is None:
            raise ApplicationError("ACTION_NOT_FOUND", "Action does not exist", 404)
        verification = await self.verifications.get_for_action(action_id, for_update=True)
        if (
            action.status != ActionRequestStatus.VERIFICATION_FAILED
            or verification is None
            or not verification.compensation_required
            or action.rollback_capability is None
        ):
            raise ApplicationError(
                "COMPENSATION_NOT_REQUIRED",
                "Only a failed Verification with rollback metadata can be compensated",
                409,
            )
        if action.rollback_capability != action.capability:
            raise ApplicationError(
                "COMPENSATION_CAPABILITY_UNSUPPORTED",
                "Cross-capability compensation is not enabled",
                409,
            )
        if parameters != action.parameters:
            raise ApplicationError(
                "COMPENSATION_PARAMETERS_INVALID",
                "Compensation parameters must match the approved Action parameters",
                422,
            )
        fingerprint = self._fingerprint(action_id, parameters)
        existing = await self.compensations.get_by_key(action.environment_id, idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ApplicationError(
                    "COMPENSATION_IDEMPOTENCY_CONFLICT",
                    "Idempotency key belongs to a different Compensation Request",
                    409,
                )
            return existing, True
        if await self.compensations.get_for_action(action_id) is not None:
            raise ApplicationError(
                "COMPENSATION_ALREADY_EXISTS",
                "An Action can have only one Compensation Request",
                409,
            )
        actor = principal_context.get()
        now = datetime.now(UTC)
        record = await self.compensations.create(
            action_request_id=action.id,
            verification_id=verification.id,
            environment_id=action.environment_id,
            incident_id=action.incident_id,
            resource_id=action.resource_id,
            capability=action.rollback_capability,
            parameters=dict(parameters),
            status=CompensationStatus.PENDING,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            requested_by=actor.actor_id if actor else "system",
            expires_at=now + timedelta(seconds=expires_in_seconds),
            version=1,
        )
        await self._event(record, "compensation.requested", now)
        await commit_session(self.session)
        return record, False

    async def decide(
        self,
        compensation_id: UUID,
        *,
        approve: bool,
        expected_version: int,
        comment: str | None,
    ) -> CompensationRequestRecord:
        record = await self._get(compensation_id, for_update=True)
        self._expected(record, expected_version)
        if record.status != CompensationStatus.PENDING:
            raise ApplicationError(
                "COMPENSATION_ALREADY_RESOLVED", "Compensation is no longer pending", 409
            )
        now = datetime.now(UTC)
        if self._as_utc(record.expires_at) <= now:
            record.status = CompensationStatus.REJECTED
            record.decision_comment = "Compensation approval expired"
        elif approve:
            actor = principal_context.get()
            if actor is not None and record.requested_by == actor.actor_id:
                raise ApplicationError(
                    "COMPENSATION_SELF_APPROVAL_FORBIDDEN",
                    "The Compensation requester cannot approve the same request",
                    403,
                )
            action = await self.actions.get(record.action_request_id)
            if action is None:
                raise ApplicationError("ACTION_NOT_FOUND", "Action does not exist", 404)
            snapshot = await self.policies.get_decision(action.policy_decision_id)
            if snapshot is None:
                raise ApplicationError("POLICY_DECISION_NOT_FOUND", "Policy decision missing", 409)
            current = await PolicyService(self.session).revalidate_snapshot(snapshot)
            if not current.allowed:
                raise ApplicationError(
                    "POLICY_REVALIDATION_FAILED",
                    f"Compensation cannot be approved: {current.reason}",
                    409,
                )
            record.status = CompensationStatus.APPROVED
            record.decision_comment = comment
        else:
            record.status = CompensationStatus.REJECTED
            record.decision_comment = comment
        actor = principal_context.get()
        record.decided_by = actor.actor_id if actor else "system"
        record.decided_at = now
        record.version += 1
        record.updated_at = now
        await self._event(record, "compensation.resolved", now)
        await InvestigationHITLService(self.session).resolve_subject(
            InvestigationHITLSubjectType.COMPENSATION,
            record.id,
            record.status.value,
            now,
        )
        await commit_session(self.session)
        return record

    async def dispatch(
        self,
        compensation_id: UUID,
        *,
        expected_version: int,
    ) -> CompensationExecutionRecord:
        await self.recover_expired()
        record = await self._get(compensation_id, for_update=True)
        self._expected(record, expected_version)
        existing = await self.executions.get_for_request(record.id)
        if existing is not None:
            return existing
        if record.status != CompensationStatus.APPROVED:
            raise ApplicationError(
                "COMPENSATION_NOT_APPROVED", "Only an approved Compensation can dispatch", 409
            )
        now = datetime.now(UTC)
        if self._as_utc(record.expires_at) <= now:
            raise ApplicationError(
                "COMPENSATION_APPROVAL_EXPIRED", "Compensation approval expired", 409
            )
        lock = await self.locks.get_for_action(record.action_request_id, for_update=True)
        if (
            lock is None
            or lock.released_at is not None
            or not lock.reconciliation_required
        ):
            raise ApplicationError(
                "COMPENSATION_RESOURCE_LOCK_INVALID",
                "Compensation requires the frozen original Resource Lock",
                409,
            )
        runner = await self._select_runner(record, now)
        if runner is None:
            raise ApplicationError(
                "COMPENSATION_RUNNER_UNAVAILABLE",
                "No online Runner advertises the compensation capability",
                409,
            )
        execution = await self.executions.create(
            compensation_request_id=record.id,
            runner_id=runner.id,
            status=CompensationStatus.DISPATCHING,
            resource_fencing_token=lock.fencing_token,
            version=1,
        )
        record.status = CompensationStatus.DISPATCHING
        record.version += 1
        record.updated_at = now
        action = await self.actions.get(record.action_request_id, for_update=True)
        if action is not None:
            action.status = ActionRequestStatus.COMPENSATING
            action.version += 1
            action.updated_at = now
        await self._event(record, "compensation.dispatched", now, execution)
        await commit_session(self.session)
        return execution

    async def claim(
        self,
        *,
        runner_id: UUID,
        access_token: str,
        runner_fencing_token: int,
    ) -> tuple[CompensationExecutionRecord, CompensationRequestRecord] | None:
        _, lease = await self.runner_service.authorize(runner_id, access_token)
        if lease.fencing_token != runner_fencing_token:
            raise ApplicationError("STALE_RUNNER_FENCING_TOKEN", "Runner token is stale", 409)
        await self.recover_expired()
        execution = await self.executions.claim_for_runner(runner_id)
        if execution is None:
            await commit_session(self.session)
            return None
        record = await self._get(execution.compensation_request_id, for_update=True)
        lock = await self.locks.get_for_action(record.action_request_id, for_update=True)
        if lock is None or lock.fencing_token != execution.resource_fencing_token:
            raise ApplicationError(
                "COMPENSATION_RESOURCE_LOCK_INVALID", "Resource Lock changed", 409
            )
        now = datetime.now(UTC)
        execution.status = CompensationStatus.RUNNING
        execution.runner_fencing_token = runner_fencing_token
        execution.lease_expires_at = now + self.execution_lease
        execution.started_at = now
        execution.version += 1
        execution.updated_at = now
        record.status = CompensationStatus.RUNNING
        record.version += 1
        record.updated_at = now
        lock.renewed_at = now
        lock.expires_at = now + self.resource_lock_lease
        lock.updated_at = now
        await self._event(record, "compensation.started", now, execution)
        await commit_session(self.session)
        return execution, record

    async def renew(
        self,
        *,
        runner_id: UUID,
        execution_id: UUID,
        access_token: str,
        execution_fencing_token: int,
        resource_fencing_token: int,
    ) -> CompensationExecutionRecord:
        await self.runner_service.authorize(runner_id, access_token)
        execution, _record, lock = await self._owned(
            runner_id, execution_id, execution_fencing_token, resource_fencing_token
        )
        now = datetime.now(UTC)
        execution.lease_expires_at = now + self.execution_lease
        execution.updated_at = now
        lock.renewed_at = now
        lock.expires_at = now + self.resource_lock_lease
        lock.updated_at = now
        await commit_session(self.session)
        return execution

    async def complete(
        self,
        *,
        runner_id: UUID,
        execution_id: UUID,
        access_token: str,
        completion_id: UUID,
        execution_fencing_token: int,
        resource_fencing_token: int,
        succeeded: bool,
        summary: str,
        error_code: str | None,
    ) -> tuple[CompensationExecutionRecord, bool]:
        await self.runner_service.authorize(runner_id, access_token)
        existing = await self.executions.get(execution_id, for_update=True)
        if existing is None:
            raise ApplicationError(
                "COMPENSATION_EXECUTION_NOT_FOUND", "Execution does not exist", 404
            )
        if existing.last_completion_id == completion_id:
            return existing, True
        execution, record, lock = await self._owned(
            runner_id, execution_id, execution_fencing_token, resource_fencing_token
        )
        now = datetime.now(UTC)
        target = CompensationStatus.SUCCEEDED if succeeded else CompensationStatus.FAILED
        execution.status = target
        execution.last_completion_id = completion_id
        execution.result_summary = summary
        execution.error_code = error_code
        execution.completed_at = now
        execution.lease_expires_at = None
        execution.version += 1
        execution.updated_at = now
        record.status = target
        record.version += 1
        record.updated_at = now
        action = await self.actions.get(record.action_request_id, for_update=True)
        if succeeded:
            lock.reconciliation_required = False
            lock.released_at = now
            lock.released_by = f"compensation:{record.id}"
            if action is not None:
                action.status = ActionRequestStatus.COMPENSATED
        else:
            lock.reconciliation_required = True
            if action is not None:
                action.status = ActionRequestStatus.ESCALATED
                record.status = CompensationStatus.ESCALATED
                record.escalation_reason = summary
        lock.expires_at = now
        lock.updated_at = now
        if action is not None:
            action.version += 1
            action.updated_at = now
        await self._event(
            record,
            "compensation.succeeded" if succeeded else "compensation.escalated",
            now,
            execution,
        )
        await commit_session(self.session)
        return execution, False

    async def escalate(
        self, compensation_id: UUID, *, expected_version: int, reason: str
    ) -> CompensationRequestRecord:
        record = await self._get(compensation_id, for_update=True)
        self._expected(record, expected_version)
        if record.status not in {
            CompensationStatus.APPROVED,
            CompensationStatus.REJECTED,
            CompensationStatus.FAILED,
            CompensationStatus.UNKNOWN,
        }:
            raise ApplicationError(
                "COMPENSATION_NOT_ESCALATABLE", "Compensation cannot be escalated", 409
            )
        now = datetime.now(UTC)
        record.status = CompensationStatus.ESCALATED
        record.escalation_reason = reason
        record.version += 1
        record.updated_at = now
        action = await self.actions.get(record.action_request_id, for_update=True)
        if action is not None:
            action.status = ActionRequestStatus.ESCALATED
            action.version += 1
            action.updated_at = now
        await self._event(record, "compensation.escalated", now)
        await commit_session(self.session)
        return record

    async def recover_expired(self) -> int:
        now = datetime.now(UTC)
        recovered = 0
        for execution in await self.executions.expired_running(now):
            record = await self._get(execution.compensation_request_id, for_update=True)
            execution.status = CompensationStatus.UNKNOWN
            execution.lease_expires_at = None
            execution.version += 1
            execution.updated_at = now
            record.status = CompensationStatus.UNKNOWN
            record.version += 1
            record.updated_at = now
            lock = await self.locks.get_for_action(record.action_request_id, for_update=True)
            if lock is not None:
                lock.reconciliation_required = True
                lock.expires_at = now
                lock.updated_at = now
            await self._event(record, "compensation.unknown", now, execution)
            recovered += 1
        if recovered:
            await commit_session(self.session)
        return recovered

    async def _owned(
        self,
        runner_id: UUID,
        execution_id: UUID,
        execution_token: int,
        resource_token: int,
    ) -> tuple[CompensationExecutionRecord, CompensationRequestRecord, ResourceLockRecord]:
        execution = await self.executions.get(execution_id, for_update=True)
        if execution is None:
            raise ApplicationError(
                "COMPENSATION_EXECUTION_NOT_FOUND", "Execution does not exist", 404
            )
        if (
            execution.runner_id != runner_id
            or execution.execution_fencing_token != execution_token
            or execution.resource_fencing_token != resource_token
        ):
            raise ApplicationError("ACTION_EXECUTION_FENCED", "Execution token is stale", 409)
        now = datetime.now(UTC)
        if (
            execution.status != CompensationStatus.RUNNING
            or execution.lease_expires_at is None
            or self._as_utc(execution.lease_expires_at) <= now
        ):
            raise ApplicationError("ACTION_NOT_RUNNING", "Compensation is not running", 409)
        record = await self._get(execution.compensation_request_id, for_update=True)
        lock = await self.locks.get_for_action(record.action_request_id, for_update=True)
        if lock is None or lock.fencing_token != resource_token:
            raise ApplicationError("ACTION_RESOURCE_LOCK_INVALID", "Resource Lock changed", 409)
        return execution, record, lock

    async def _select_runner(
        self, record: CompensationRequestRecord, now: datetime
    ) -> RunnerRecord | None:
        for runner in await self.runners.online_for_environment(record.environment_id, now):
            connectors = runner.capabilities.get("connectors", [])
            if isinstance(connectors, list) and any(
                isinstance(item, dict) and record.capability in item.get("actions", [])
                for item in connectors
            ):
                return runner
        return None

    async def _get(
        self, compensation_id: UUID, *, for_update: bool = False
    ) -> CompensationRequestRecord:
        record = await self.compensations.get(compensation_id, for_update=for_update)
        if record is None:
            raise ApplicationError(
                "COMPENSATION_NOT_FOUND", "Compensation Request does not exist", 404
            )
        return record

    async def _event(
        self,
        record: CompensationRequestRecord,
        event_type: str,
        now: datetime,
        execution: CompensationExecutionRecord | None = None,
    ) -> None:
        incident = await self.incidents.get(record.incident_id)
        if incident is not None:
            await self.events.record(
                incident,
                event_type,
                now,
                "runner" if execution and execution.started_at else "user",
                {
                    "compensationId": str(record.id),
                    "actionId": str(record.action_request_id),
                    "executionId": str(execution.id) if execution else None,
                    "status": record.status.value,
                },
                aggregate_type="compensation_request",
                aggregate_id=record.id,
                aggregate_version=record.version,
            )

    @staticmethod
    def _expected(record: CompensationRequestRecord, expected_version: int) -> None:
        if record.version != expected_version:
            raise ApplicationError(
                "COMPENSATION_VERSION_CONFLICT", "Compensation changed; reload", 409
            )

    @staticmethod
    def _fingerprint(action_id: UUID, parameters: dict[str, object]) -> str:
        encoded = json.dumps(
            {"actionId": str(action_id), "parameters": parameters},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode()).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
