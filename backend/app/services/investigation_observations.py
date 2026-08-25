from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.investigations import (
    InvestigationObservationWaitStatus,
    InvestigationRunStatus,
)
from app.domain.plans import PlanStatus, PlanStepStatus, PlanStepType
from app.domain.runner_tasks import RunnerReadOperation
from app.services.events import EventRecorder
from app.services.observation_specs import TrustedObservationSpecCompiler
from app.services.runner_tasks import RunnerTaskService
from app.storage.models import (
    InvestigationCheckpointRecord,
    InvestigationObservationWaitRecord,
)
from app.storage.repositories import (
    IncidentRepository,
    InvestigationRepository,
    PlanRepository,
    ResourceRepository,
)
from app.storage.transactions import commit_session


class InvestigationObservationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        runner_lease_seconds: int = 60,
        task_lease_seconds: int = 120,
        max_output_bytes: int = 65536,
    ) -> None:
        self.session = session
        self.runs = InvestigationRepository(session)
        self.incidents = IncidentRepository(session)
        self.resources = ResourceRepository(session)
        self.plans = PlanRepository(session)
        self.events = EventRecorder(session)
        self.compiler = TrustedObservationSpecCompiler()
        self.tasks = RunnerTaskService(
            session,
            runner_lease_seconds=runner_lease_seconds,
            task_lease_seconds=task_lease_seconds,
            max_output_bytes=max_output_bytes,
        )

    async def start_wait(
        self,
        *,
        run_id: UUID,
        checkpoint: InvestigationCheckpointRecord,
        node_execution_id: str,
        expected_run_version: int,
        plan_step_id: UUID,
        resource_id: UUID,
        operation: RunnerReadOperation,
        purpose: str,
        model_requests: int,
        model_input_tokens: int,
        model_output_tokens: int,
        output_summary: str,
    ) -> tuple[InvestigationObservationWaitRecord, bool]:
        existing = await self.runs.get_observation_wait_by_execution(
            run_id, node_execution_id
        )
        if existing is not None:
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
                "An Observation wait can only interrupt a running investigation",
                409,
            )
        if checkpoint.run_id != run.id:
            raise ApplicationError(
                "INVESTIGATION_CHECKPOINT_NOT_FOUND",
                "Observation checkpoint must belong to the investigation run",
                422,
            )
        incident = await self.incidents.get(run.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        resource = await self.resources.get(resource_id)
        if resource is None or incident.resource_id != resource.id:
            raise ApplicationError(
                "OBSERVATION_RESOURCE_OUT_OF_SCOPE",
                "Observation Resource must be the Incident Resource",
                422,
            )
        step = await self.plans.get_step_for_incident(
            incident.id, plan_step_id, for_update=True
        )
        plan = await self.plans.get(step.plan_id) if step is not None else None
        if (
            step is None
            or plan is None
            or plan.status != PlanStatus.ACTIVE
            or step.status != PlanStepStatus.RUNNING
            or step.step_type
            not in {
                PlanStepType.OBSERVE,
                PlanStepType.ANALYZE,
                PlanStepType.EXPERIMENT,
                PlanStepType.VERIFY,
            }
        ):
            raise ApplicationError(
                "OBSERVATION_PLAN_STEP_INVALID",
                "Observation requires a running observational PlanStep",
                409,
            )

        task_input = self.compiler.compile(
            incident_id=incident.id,
            plan_step_id=step.id,
            resource_id=resource.id,
            resource_attributes=resource.attributes,
            operation=operation,
            idempotency_key=f"agent-observation:{node_execution_id}",
        )
        task = await self.tasks.create(
            incident_id=task_input.incident_id,
            plan_step_id=task_input.plan_step_id,
            resource_id=task_input.resource_id,
            runner_id=task_input.runner_id,
            connector=task_input.connector,
            operation=task_input.operation,
            parameters=task_input.parameters,
            idempotency_key=task_input.idempotency_key,
            timeout_seconds=task_input.timeout_seconds,
            max_attempts=task_input.max_attempts,
            commit=False,
        )
        now = datetime.now(UTC)
        wait = await self.runs.create_observation_wait(
            run_id=run.id,
            incident_id=incident.id,
            checkpoint_id=checkpoint.id,
            plan_step_id=step.id,
            runner_task_id=task.id,
            node_execution_id=node_execution_id,
            operation=operation.value,
            purpose=purpose,
            status=InvestigationObservationWaitStatus.WAITING,
            model_requests=model_requests,
            model_input_tokens=model_input_tokens,
            model_output_tokens=model_output_tokens,
            output_summary=output_summary,
            version=1,
        )
        run.status = InvestigationRunStatus.PAUSED
        run.runtime_owner = None
        run.runtime_lease_expires_at = None
        run.version += 1
        run.updated_at = now
        await self.events.record(
            incident,
            "investigation.observation_wait_started",
            now,
            "agent_runtime",
            {
                "runId": str(run.id),
                "waitId": str(wait.id),
                "checkpointId": str(checkpoint.id),
                "runnerTaskId": str(task.id),
                "planStepId": str(step.id),
                "operation": operation.value,
                "version": run.version,
            },
            aggregate_type="investigation_run",
            aggregate_id=run.id,
            aggregate_version=run.version,
        )
        await commit_session(self.session)
        return wait, False

    async def resolve_task(
        self,
        *,
        runner_task_id: UUID,
        outcome: str,
        evidence_id: UUID | None,
        actor: str,
        now: datetime,
    ) -> InvestigationObservationWaitRecord | None:
        wait = await self.runs.get_waiting_observation_for_task(runner_task_id)
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

        wait.status = InvestigationObservationWaitStatus.RESOLVED
        wait.outcome = outcome
        wait.evidence_id = evidence_id
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
            "investigation.observation_wait_resolved",
            now,
            actor,
            {
                "runId": str(run.id),
                "waitId": str(wait.id),
                "runnerTaskId": str(runner_task_id),
                "outcome": outcome,
                "evidenceId": str(evidence_id) if evidence_id else None,
                "runStatus": run.status.value,
                "version": run.version,
            },
            aggregate_type="investigation_run",
            aggregate_id=run.id,
            aggregate_version=run.version,
        )
        return wait
