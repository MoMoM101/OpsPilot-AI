from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.actions import ActionRequestStatus, ActionVerificationStatus
from app.domain.runner_tasks import RunnerTaskStatus
from app.services.action_capabilities import action_capability_definition
from app.services.events import EventRecorder
from app.storage.models import (
    ActionExecutionRecord,
    ActionRequestRecord,
    ActionVerificationRecord,
    RunnerTaskRecord,
)
from app.storage.repositories import (
    ActionExecutionRepository,
    ActionRequestRepository,
    ActionVerificationRepository,
    IncidentRepository,
    ResourceLockRepository,
    RunnerTaskRepository,
)


class ActionVerificationService:
    """Compiles trusted Action metadata into bounded read-only verification tasks."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.verifications = ActionVerificationRepository(session)
        self.tasks = RunnerTaskRepository(session)
        self.actions = ActionRequestRepository(session)
        self.executions = ActionExecutionRepository(session)
        self.locks = ResourceLockRepository(session)
        self.incidents = IncidentRepository(session)
        self.events = EventRecorder(session)

    async def create(
        self,
        action: ActionRequestRecord,
        execution: ActionExecutionRecord,
        now: datetime,
    ) -> tuple[ActionVerificationRecord, RunnerTaskRecord]:
        existing = await self.verifications.get_for_action(action.id)
        if existing is not None:
            task = await self.tasks.get_for_verification(existing.id)
            if task is None:
                raise RuntimeError("Action Verification has no Runner task")
            return existing, task
        connector, operation, parameters = self._spec(action)
        verification = await self.verifications.create(
            action_request_id=action.id,
            environment_id=action.environment_id,
            incident_id=action.incident_id,
            resource_id=action.resource_id,
            status=ActionVerificationStatus.QUEUED,
            criteria_snapshot=list(action.verification_criteria),
            connector=connector,
            operation=operation,
            parameters=parameters,
            compensation_required=False,
            version=1,
        )
        task = await self.tasks.create(
            incident_id=action.incident_id,
            plan_step_id=None,
            action_verification_id=verification.id,
            resource_id=action.resource_id,
            runner_id=execution.runner_id,
            connector=connector,
            operation=operation,
            parameters=parameters,
            status=RunnerTaskStatus.QUEUED,
            idempotency_key=f"action-verification:{action.id}",
            timeout_seconds=30,
            max_attempts=3,
            attempt=0,
        )
        incident = await self.incidents.get(action.incident_id)
        if incident is not None:
            await self.events.record(
                incident,
                "action.verification_queued",
                now,
                "control_plane",
                {
                    "actionId": str(action.id),
                    "verificationId": str(verification.id),
                    "taskId": str(task.id),
                    "operation": operation,
                },
                aggregate_type="action_verification",
                aggregate_id=verification.id,
                aggregate_version=verification.version,
            )
        return verification, task

    async def mark_running(self, task: RunnerTaskRecord, now: datetime) -> None:
        if task.action_verification_id is None:
            return
        verification = await self.verifications.get(task.action_verification_id, for_update=True)
        if verification is None or verification.status != ActionVerificationStatus.QUEUED:
            return
        verification.status = ActionVerificationStatus.RUNNING
        verification.started_at = verification.started_at or now
        verification.version += 1
        verification.updated_at = now

    async def finalize_task(
        self,
        task: RunnerTaskRecord,
        *,
        succeeded: bool,
        now: datetime | None = None,
    ) -> None:
        if task.action_verification_id is None:
            return
        completed_at = now or datetime.now(UTC)
        verification = await self.verifications.get(task.action_verification_id, for_update=True)
        if verification is None or verification.status in {
            ActionVerificationStatus.PASSED,
            ActionVerificationStatus.FAILED,
        }:
            return
        if not succeeded and task.attempt < task.max_attempts:
            task.status = RunnerTaskStatus.QUEUED
            task.runner_id = None
            task.task_fencing_token = None
            task.completed_at = None
            task.lease_expires_at = None
            verification.status = ActionVerificationStatus.QUEUED
            verification.error_code = task.error_code
            verification.result_summary = task.result_summary
            verification.version += 1
            verification.updated_at = completed_at
            return

        action = await self.actions.get(verification.action_request_id, for_update=True)
        execution = await self.executions.get_for_action(
            verification.action_request_id, for_update=True
        )
        if action is None or execution is None:
            raise RuntimeError("Action Verification lost its Action or Execution")
        verification.status = (
            ActionVerificationStatus.PASSED if succeeded else ActionVerificationStatus.FAILED
        )
        verification.result_summary = task.result_summary
        verification.error_code = task.error_code
        verification.evidence_id = task.evidence_id
        verification.completed_at = completed_at
        verification.compensation_required = not succeeded and bool(action.rollback_capability)
        verification.version += 1
        verification.updated_at = completed_at
        target = (
            ActionRequestStatus.SUCCEEDED if succeeded else ActionRequestStatus.VERIFICATION_FAILED
        )
        action.status = target
        action.version += 1
        action.updated_at = completed_at
        execution.status = target
        execution.version += 1
        execution.updated_at = completed_at
        lock = await self.locks.get_for_action(action.id, for_update=True)
        if lock is not None:
            if succeeded:
                lock.released_at = completed_at
                lock.released_by = "verification"
                lock.reconciliation_required = False
            else:
                lock.reconciliation_required = True
            lock.expires_at = completed_at
            lock.updated_at = completed_at
        incident = await self.incidents.get(action.incident_id)
        if incident is not None:
            event_type = "action.verification_passed" if succeeded else "action.verification_failed"
            await self.events.record(
                incident,
                event_type,
                completed_at,
                "runner",
                {
                    "actionId": str(action.id),
                    "verificationId": str(verification.id),
                    "taskId": str(task.id),
                    "evidenceId": str(task.evidence_id) if task.evidence_id else None,
                    "compensationRequired": verification.compensation_required,
                },
                aggregate_type="action_verification",
                aggregate_id=verification.id,
                aggregate_version=verification.version,
            )

    @staticmethod
    def _spec(action: ActionRequestRecord) -> tuple[str, str, dict[str, object]]:
        definition = action_capability_definition(action.capability)
        if (
            definition is not None
            and definition.execution_connector is not None
            and definition.verification_operation is not None
            and definition.verification_parameter_key is not None
        ):
            return (
                definition.execution_connector,
                definition.verification_operation,
                {
                    definition.verification_parameter_key: action.parameters[
                        definition.parameter_key
                    ]
                },
            )
        raise RuntimeError(f"No trusted verification mapping for {action.capability}")
