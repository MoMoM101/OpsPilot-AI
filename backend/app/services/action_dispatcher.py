from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.actions import ActionRequestStatus
from app.services.action_capabilities import action_capability_definition
from app.services.action_verifications import ActionVerificationService
from app.services.events import EventRecorder
from app.services.resource_locks import ResourceLockService
from app.services.runners import RunnerService
from app.storage.models import (
    ActionExecutionRecord,
    ActionRequestRecord,
    ResourceLockRecord,
    RunnerRecord,
)
from app.storage.repositories import (
    ActionExecutionRepository,
    ActionRequestRepository,
    IncidentRepository,
    ResourceLockRepository,
    RunnerRepository,
)
from app.storage.transactions import commit_session


class ActionDispatcherService:
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
        self.actions = ActionRequestRepository(session)
        self.executions = ActionExecutionRepository(session)
        self.locks = ResourceLockRepository(session)
        self.runners = RunnerRepository(session)
        self.incidents = IncidentRepository(session)
        self.events = EventRecorder(session)
        self.runner_service = RunnerService(
            session,
            runner_lease_seconds,
            token_rotation_seconds=runner_token_rotation_seconds,
            token_ttl_seconds=runner_token_ttl_seconds,
            token_grace_seconds=runner_token_grace_seconds,
        )

    async def dispatch(self, action_id: UUID) -> ActionExecutionRecord:
        await self.recover_expired()
        action = await self.actions.get(action_id, for_update=True)
        if action is None:
            raise ApplicationError("ACTION_NOT_FOUND", "Action Request does not exist", 404)
        existing = await self.executions.get_for_action(action_id)
        if existing is not None:
            return existing
        if action.status != ActionRequestStatus.READY:
            raise ApplicationError(
                "ACTION_NOT_DISPATCHABLE", "Only a ready Action can be dispatched", 409
            )
        now = datetime.now(UTC)
        lock, _duplicate = await ResourceLockService(
            self.session, int(self.resource_lock_lease.total_seconds())
        ).acquire(action_id, commit=False)
        runner = await self._select_runner(action, now)
        if runner is None:
            raise ApplicationError(
                "ACTION_RUNNER_UNAVAILABLE",
                "No online Runner advertises the required Action capability",
                409,
            )
        execution = await self.executions.create(
            action_request_id=action.id,
            runner_id=runner.id,
            status=ActionRequestStatus.DISPATCHING,
            resource_fencing_token=lock.fencing_token,
        )
        action.status = ActionRequestStatus.DISPATCHING
        action.version += 1
        action.updated_at = now
        await self._event(action, execution, "action.dispatched", now)
        await commit_session(self.session)
        return execution

    async def claim(
        self,
        *,
        runner_id: UUID,
        access_token: str,
        runner_fencing_token: int,
    ) -> tuple[ActionExecutionRecord, ActionRequestRecord] | None:
        _, runner_lease = await self.runner_service.authorize(runner_id, access_token)
        if runner_lease.fencing_token != runner_fencing_token:
            raise ApplicationError(
                "STALE_RUNNER_FENCING_TOKEN", "Runner fencing token is stale", 409
            )
        await self.recover_expired()
        execution = await self.executions.claim_for_runner(runner_id)
        if execution is None:
            await commit_session(self.session)
            return None
        action = await self.actions.get(execution.action_request_id, for_update=True)
        if action is None:
            raise ApplicationError("ACTION_NOT_FOUND", "Action Request does not exist", 404)
        lock = await self.locks.get_for_action(action.id, for_update=True)
        now = datetime.now(UTC)
        if lock is None or lock.fencing_token != execution.resource_fencing_token:
            raise ApplicationError("ACTION_RESOURCE_LOCK_INVALID", "Resource Lock changed", 409)
        execution.status = ActionRequestStatus.RUNNING
        execution.runner_fencing_token = runner_fencing_token
        execution.lease_expires_at = now + self.execution_lease
        execution.started_at = now
        execution.version += 1
        execution.updated_at = now
        action.status = ActionRequestStatus.RUNNING
        action.version += 1
        action.updated_at = now
        lock.renewed_at = now
        lock.expires_at = now + self.resource_lock_lease
        lock.updated_at = now
        await self._event(action, execution, "action.started", now)
        await commit_session(self.session)
        return execution, action

    async def renew(
        self,
        *,
        runner_id: UUID,
        execution_id: UUID,
        access_token: str,
        execution_fencing_token: int,
        resource_fencing_token: int,
    ) -> ActionExecutionRecord:
        await self.runner_service.authorize(runner_id, access_token)
        execution, _action, lock = await self._owned_running(
            runner_id,
            execution_id,
            execution_fencing_token,
            resource_fencing_token,
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
    ) -> tuple[ActionExecutionRecord, bool]:
        await self.runner_service.authorize(runner_id, access_token)
        execution = await self.executions.get(execution_id, for_update=True)
        if execution is None:
            raise ApplicationError("ACTION_EXECUTION_NOT_FOUND", "Execution not found", 404)
        if execution.last_completion_id == completion_id:
            return execution, True
        execution, action, lock = await self._owned_running(
            runner_id,
            execution_id,
            execution_fencing_token,
            resource_fencing_token,
        )
        now = datetime.now(UTC)
        target = ActionRequestStatus.APPLIED if succeeded else ActionRequestStatus.FAILED
        execution.status = target
        execution.last_completion_id = completion_id
        execution.result_summary = summary
        execution.error_code = error_code
        execution.completed_at = now
        execution.lease_expires_at = None
        execution.version += 1
        execution.updated_at = now
        action.status = ActionRequestStatus.VERIFYING if succeeded else target
        action.version += 1
        action.updated_at = now
        if succeeded:
            lock.reconciliation_required = True
            lock.expires_at = now
            lock.updated_at = now
            await ActionVerificationService(self.session).create(action, execution, now)
            event_type = "action.applied"
        else:
            lock.released_at = now
            lock.released_by = f"runner:{runner_id}"
            lock.expires_at = now
            lock.updated_at = now
            event_type = "action.failed"
        await self._event(action, execution, event_type, now)
        await commit_session(self.session)
        return execution, False

    async def recover_expired(self) -> int:
        now = datetime.now(UTC)
        recovered = 0
        for execution in await self.executions.expired_running(now):
            action = await self.actions.get(execution.action_request_id, for_update=True)
            if action is None:
                continue
            lock = await self.locks.get_for_action(action.id, for_update=True)
            execution.status = ActionRequestStatus.UNKNOWN
            execution.lease_expires_at = None
            execution.version += 1
            execution.updated_at = now
            action.status = ActionRequestStatus.UNKNOWN
            action.version += 1
            action.updated_at = now
            if lock is not None:
                lock.reconciliation_required = True
                lock.expires_at = now
                lock.updated_at = now
            await self._event(action, execution, "action.unknown", now)
            recovered += 1
        if recovered:
            await commit_session(self.session)
        return recovered

    async def reconcile(
        self,
        action_id: UUID,
        *,
        expected_version: int,
        succeeded: bool,
        summary: str,
        error_code: str | None,
    ) -> ActionExecutionRecord:
        action = await self.actions.get(action_id, for_update=True)
        execution = await self.executions.get_for_action(action_id, for_update=True)
        if action is None or execution is None:
            raise ApplicationError("ACTION_NOT_FOUND", "Action or execution not found", 404)
        if action.version != expected_version:
            raise ApplicationError("ACTION_VERSION_CONFLICT", "Action changed; reload", 409)
        if action.status != ActionRequestStatus.UNKNOWN:
            raise ApplicationError(
                "ACTION_NOT_RECONCILABLE", "Only an unknown Action can be reconciled", 409
            )
        now = datetime.now(UTC)
        target = ActionRequestStatus.SUCCEEDED if succeeded else ActionRequestStatus.FAILED
        action.status = target
        action.version += 1
        action.updated_at = now
        execution.status = target
        execution.result_summary = summary
        execution.error_code = error_code
        execution.completed_at = now
        execution.version += 1
        execution.updated_at = now
        lock = await self.locks.get_for_action(action.id, for_update=True)
        if lock is not None:
            lock.reconciliation_required = False
            lock.released_at = now
            lock.released_by = "reconciliation"
            lock.expires_at = now
            lock.updated_at = now
        await self._event(action, execution, "action.reconciled", now)
        await commit_session(self.session)
        return execution

    async def _select_runner(
        self, action: ActionRequestRecord, now: datetime
    ) -> RunnerRecord | None:
        for runner in await self.runners.online_for_environment(action.environment_id, now):
            connectors = runner.capabilities.get("connectors", [])
            if not isinstance(connectors, list):
                continue
            verification_operation = self._verification_operation(action.capability)
            for connector in connectors:
                if (
                    isinstance(connector, dict)
                    and action.capability in connector.get("actions", [])
                    and verification_operation in connector.get("observe", [])
                ):
                    return runner
        return None

    async def _owned_running(
        self,
        runner_id: UUID,
        execution_id: UUID,
        execution_fencing_token: int,
        resource_fencing_token: int,
    ) -> tuple[ActionExecutionRecord, ActionRequestRecord, ResourceLockRecord]:
        execution = await self.executions.get(execution_id, for_update=True)
        if execution is None:
            raise ApplicationError("ACTION_EXECUTION_NOT_FOUND", "Execution not found", 404)
        if (
            execution.runner_id != runner_id
            or execution.execution_fencing_token != execution_fencing_token
            or execution.resource_fencing_token != resource_fencing_token
        ):
            raise ApplicationError("ACTION_EXECUTION_FENCED", "Execution token is stale", 409)
        now = datetime.now(UTC)
        if execution.status != ActionRequestStatus.RUNNING:
            raise ApplicationError("ACTION_NOT_RUNNING", "Action is not running", 409)
        if execution.lease_expires_at is None or self._as_utc(execution.lease_expires_at) <= now:
            await self.recover_expired()
            raise ApplicationError("ACTION_EXECUTION_LEASE_EXPIRED", "Lease expired", 409)
        action = await self.actions.get(execution.action_request_id, for_update=True)
        lock = await self.locks.get_for_action(execution.action_request_id, for_update=True)
        if action is None or lock is None or lock.fencing_token != resource_fencing_token:
            raise ApplicationError("ACTION_RESOURCE_LOCK_INVALID", "Resource Lock changed", 409)
        return execution, action, lock

    async def _event(
        self,
        action: ActionRequestRecord,
        execution: ActionExecutionRecord,
        event_type: str,
        now: datetime,
    ) -> None:
        incident = await self.incidents.get(action.incident_id)
        if incident is not None:
            await self.events.record(
                incident,
                event_type,
                now,
                "runner",
                {
                    "actionId": str(action.id),
                    "executionId": str(execution.id),
                    "runnerId": str(execution.runner_id),
                    "status": execution.status.value,
                },
                aggregate_type="action_execution",
                aggregate_id=execution.id,
                aggregate_version=execution.version,
            )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @staticmethod
    def _verification_operation(capability: str) -> str:
        definition = action_capability_definition(capability)
        if definition is None:
            return ""
        return definition.verification_operation or ""
