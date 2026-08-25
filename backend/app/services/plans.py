from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.incidents import IncidentStatus
from app.domain.plans import (
    PlanStatus,
    PlanStepRisk,
    PlanStepStatus,
    PlanStepType,
    transition_plan_step,
)
from app.domain.runner_tasks import RunnerTaskStatus
from app.services.events import EventRecorder
from app.storage.models import IncidentRecord, PlanStepRecord, RunnerTaskRecord
from app.storage.repositories import (
    EvidenceRepository,
    IncidentRepository,
    PlanRepository,
    RunnerTaskRepository,
)
from app.storage.transactions import commit_session

_PLANNABLE_INCIDENT_STATUSES = {
    IncidentStatus.INVESTIGATING,
    IncidentStatus.DIAGNOSED,
    IncidentStatus.PLANNING,
}


@dataclass(frozen=True, slots=True)
class PlanStepInput:
    title: str
    objective: str
    step_type: PlanStepType
    dependencies: list[str]
    resource_scope: list[str]
    allowed_capabilities: list[str]
    expected_evidence: list[str]
    success_criteria: list[str]
    risk: PlanStepRisk


class PlanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.incidents = IncidentRepository(session)
        self.plans = PlanRepository(session)
        self.evidence = EvidenceRepository(session)
        self.runner_tasks = RunnerTaskRepository(session)
        self.events = EventRecorder(session)

    async def create(
        self,
        incident_id: UUID,
        objective: str,
        max_tool_calls: int,
        max_duration_seconds: int,
        steps: list[PlanStepInput],
    ) -> UUID:
        self._validate_plan_dependencies(steps)
        incident = await self.incidents.get(incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        if incident.status not in _PLANNABLE_INCIDENT_STATUSES:
            raise ApplicationError(
                "INCIDENT_NOT_PLANNABLE",
                f"Cannot create plan while incident is {incident.status.value}",
                409,
            )

        previous_plan = await self.plans.get_latest(incident_id)
        plan_version = previous_plan.version + 1 if previous_plan else 1
        replan_count = previous_plan.replan_count + 1 if previous_plan else 0
        if previous_plan and previous_plan.status == PlanStatus.ACTIVE:
            previous_plan.status = PlanStatus.SUPERSEDED
            await self._cancel_runner_tasks(
                incident,
                await self.runner_tasks.active_for_plan(previous_plan.id),
                datetime.now(UTC),
                "PLAN_SUPERSEDED",
            )

        plan = await self.plans.create(
            incident_id,
            plan_version,
            objective,
            max_tool_calls,
            max_duration_seconds,
            replan_count,
        )
        for ordinal, step in enumerate(steps, start=1):
            await self.plans.add_step(
                plan.id,
                ordinal,
                step.title,
                step.objective,
                step.step_type,
                step.dependencies,
                step.resource_scope,
                step.allowed_capabilities,
                step.expected_evidence,
                step.success_criteria,
                step.risk,
            )

        incident.replan_count = replan_count
        incident.tool_budget_limit = max_tool_calls
        incident.updated_at = datetime.now(UTC)
        await self.events.record(
            incident,
            "plan.created" if plan_version == 1 else "plan.updated",
            incident.updated_at,
            "agent",
            {"plan_id": str(plan.id), "version": plan_version},
            aggregate_type="plan",
            aggregate_id=plan.id,
            aggregate_version=plan.version,
        )
        await commit_session(self.session)
        return plan.id

    async def transition_step(
        self,
        incident_id: UUID,
        step_id: UUID,
        target: PlanStepStatus,
        expected_version: int,
        evidence_ids: list[str],
        result_summary: str | None,
    ) -> None:
        step = await self.plans.get_step_for_incident(
            incident_id,
            step_id,
            for_update=True,
        )
        if step is None:
            raise ApplicationError("PLAN_STEP_NOT_FOUND", "Plan step does not exist", 404)
        if step.version != expected_version:
            raise ApplicationError(
                "PLAN_STEP_VERSION_CONFLICT",
                "Plan step has changed; reload before retrying",
                409,
            )
        plan = await self.plans.get(step.plan_id)
        if plan is None:
            raise ApplicationError("PLAN_NOT_FOUND", "Plan does not exist", 404)
        if plan.status != PlanStatus.ACTIVE:
            raise ApplicationError(
                "PLAN_NOT_ACTIVE",
                "Only steps in the active plan can be updated",
                409,
            )
        incident = await self.incidents.get(incident_id)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        all_steps = await self.plans.list_steps(plan.id)
        if target == PlanStepStatus.RUNNING:
            self._validate_dependencies_ready(step, all_steps)
        if evidence_ids:
            await self._validate_evidence_ids(incident_id, evidence_ids)
        previous = step.status
        try:
            step.status = transition_plan_step(previous, target)
        except ValueError as exc:
            raise ApplicationError("INVALID_PLAN_STEP_TRANSITION", str(exc), 409) from exc
        if target == PlanStepStatus.RUNNING:
            step.attempts += 1
        if evidence_ids:
            step.evidence_ids = evidence_ids
        if result_summary is not None:
            step.result_summary = result_summary
        step.version += 1
        step.updated_at = datetime.now(UTC)

        if all(
            item.status in {PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED} for item in all_steps
        ):
            plan.status = PlanStatus.COMPLETED
            plan.updated_at = step.updated_at

        await self.events.record(
            incident,
            "step.updated",
            step.updated_at,
            "agent",
            {
                "step_id": str(step.id),
                "from": previous.value,
                "to": target.value,
                "version": step.version,
            },
            aggregate_type="plan_step",
            aggregate_id=step.id,
            aggregate_version=step.version,
        )
        if target in {
            PlanStepStatus.COMPLETED,
            PlanStepStatus.FAILED,
            PlanStepStatus.SKIPPED,
            PlanStepStatus.BLOCKED,
        }:
            await self._cancel_runner_tasks(
                incident,
                await self.runner_tasks.active_for_plan_step(step.id),
                step.updated_at,
                f"PLAN_STEP_{target.value.upper()}",
            )
        await commit_session(self.session)

    async def _cancel_runner_tasks(
        self,
        incident: IncidentRecord,
        tasks: list[RunnerTaskRecord],
        occurred_at: datetime,
        reason: str,
    ) -> None:
        for task in tasks:
            task.status = RunnerTaskStatus.CANCELLED
            task.lease_expires_at = None
            task.task_fencing_token = None
            task.error_code = reason
            task.result_summary = "Runner task cancelled because its investigation path ended"
            task.completed_at = occurred_at
            task.updated_at = occurred_at
            await self.events.record(
                incident,
                "runner_task.cancelled",
                occurred_at,
                "agent",
                {
                    "taskId": str(task.id),
                    "planStepId": str(task.plan_step_id) if task.plan_step_id else None,
                    "reason": reason,
                },
                aggregate_type="runner_task",
                aggregate_id=task.id,
                aggregate_version=task.attempt + 2,
            )
            from app.services.investigation_observations import (
                InvestigationObservationService,
            )

            await InvestigationObservationService(self.session).resolve_task(
                runner_task_id=task.id,
                outcome="cancelled",
                evidence_id=None,
                actor="agent",
                now=occurred_at,
            )

    @staticmethod
    def _validate_plan_dependencies(steps: list[PlanStepInput]) -> None:
        for ordinal, step in enumerate(steps, start=1):
            seen: set[int] = set()
            for dependency in step.dependencies:
                try:
                    dependency_ordinal = int(dependency)
                except ValueError as exc:
                    raise ApplicationError(
                        "INVALID_PLAN_DEPENDENCY",
                        "Plan dependencies must reference a preceding step ordinal",
                        422,
                    ) from exc
                if str(dependency_ordinal) != dependency or not 1 <= dependency_ordinal < ordinal:
                    raise ApplicationError(
                        "INVALID_PLAN_DEPENDENCY",
                        "Plan dependencies must reference a preceding step ordinal",
                        422,
                    )
                if dependency_ordinal in seen:
                    raise ApplicationError(
                        "DUPLICATE_PLAN_DEPENDENCY",
                        "A plan step cannot repeat the same dependency",
                        422,
                    )
                seen.add(dependency_ordinal)

    @staticmethod
    def _validate_dependencies_ready(
        step: PlanStepRecord,
        all_steps: list[PlanStepRecord],
    ) -> None:
        by_ordinal = {item.ordinal: item for item in all_steps}
        unmet: list[str] = []
        for dependency in step.dependencies:
            dependency_step = by_ordinal.get(int(dependency))
            if dependency_step is None or dependency_step.status not in {
                PlanStepStatus.COMPLETED,
                PlanStepStatus.SKIPPED,
            }:
                unmet.append(dependency)
        if unmet:
            raise ApplicationError(
                "PLAN_STEP_DEPENDENCIES_UNMET",
                f"Plan step dependencies are not complete: {', '.join(unmet)}",
                409,
            )

    async def _validate_evidence_ids(
        self,
        incident_id: UUID,
        evidence_ids: list[str],
    ) -> None:
        try:
            requested = {UUID(item) for item in evidence_ids}
        except ValueError as exc:
            raise ApplicationError(
                "INVALID_EVIDENCE_ID",
                "Plan step Evidence IDs must be UUIDs",
                422,
            ) from exc
        existing = await self.evidence.existing_ids_for_incident(incident_id, requested)
        if existing != requested:
            raise ApplicationError(
                "PLAN_STEP_EVIDENCE_NOT_FOUND",
                "All Evidence IDs must belong to the Incident",
                422,
            )
