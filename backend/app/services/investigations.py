from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.incidents import IncidentStatus
from app.domain.investigations import (
    InvestigationGraphDefinition,
    InvestigationHITLWaitStatus,
    InvestigationObservationWaitStatus,
    InvestigationRunStatus,
    get_investigation_graph,
    transition_investigation_run,
)
from app.domain.runner_tasks import RunnerTaskStatus
from app.services.events import EventRecorder
from app.storage.models import InvestigationCheckpointRecord, InvestigationRunRecord
from app.storage.repositories import (
    EvidenceRepository,
    HypothesisRepository,
    IncidentRepository,
    InvestigationRepository,
    PlanRepository,
    RunnerTaskRepository,
)
from app.storage.transactions import commit_session

_RUNNABLE_INCIDENT_STATUSES = {
    IncidentStatus.INVESTIGATING,
    IncidentStatus.DIAGNOSED,
    IncidentStatus.PLANNING,
}
_TERMINAL_RUN_STATUSES = {
    InvestigationRunStatus.COMPLETED,
    InvestigationRunStatus.FAILED,
    InvestigationRunStatus.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class CheckpointWriteResult:
    checkpoint: InvestigationCheckpointRecord
    run_version: int
    duplicate: bool


class InvestigationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.incidents = IncidentRepository(session)
        self.runs = InvestigationRepository(session)
        self.plans = PlanRepository(session)
        self.hypotheses = HypothesisRepository(session)
        self.evidence = EvidenceRepository(session)
        self.events = EventRecorder(session)
        self.runner_tasks = RunnerTaskRepository(session)

    async def create_run(
        self,
        *,
        incident_id: UUID,
        idempotency_key: str,
        graph_version: str,
        max_iterations: int,
        max_model_requests: int,
    ) -> InvestigationRunRecord:
        self._require_graph(graph_version, unavailable_status=422)
        existing = await self.runs.get_run_by_idempotency_key(idempotency_key)
        if existing is not None:
            if (
                existing.incident_id != incident_id
                or existing.graph_version != graph_version
                or existing.max_iterations != max_iterations
                or existing.model_request_limit != max_model_requests
            ):
                raise ApplicationError(
                    "INVESTIGATION_RUN_IDEMPOTENCY_CONFLICT",
                    "Idempotency key is already used by a different run",
                    409,
                )
            return existing

        incident = await self.incidents.get(incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        concurrent_existing = await self.runs.get_run_by_idempotency_key(idempotency_key)
        if concurrent_existing is not None:
            if (
                concurrent_existing.incident_id == incident_id
                and concurrent_existing.graph_version == graph_version
                and concurrent_existing.max_iterations == max_iterations
                and concurrent_existing.model_request_limit == max_model_requests
            ):
                return concurrent_existing
            raise ApplicationError(
                "INVESTIGATION_RUN_IDEMPOTENCY_CONFLICT",
                "Idempotency key is already used by a different run",
                409,
            )
        if incident.status not in _RUNNABLE_INCIDENT_STATUSES:
            raise ApplicationError(
                "INCIDENT_NOT_RUNNABLE",
                f"Cannot start an investigation run while incident is {incident.status.value}",
                409,
            )
        if await self.runs.get_active_for_incident(incident_id) is not None:
            raise ApplicationError(
                "ACTIVE_INVESTIGATION_RUN_EXISTS",
                "Incident already has an active investigation run",
                409,
            )

        now = datetime.now(UTC)
        run = await self.runs.create_run(
            incident_id=incident_id,
            thread_id=uuid4(),
            idempotency_key=idempotency_key,
            status=InvestigationRunStatus.QUEUED,
            graph_version=graph_version,
            max_iterations=max_iterations,
            iteration_count=0,
            last_checkpoint_sequence=0,
            model_request_limit=max_model_requests,
            model_requests_used=0,
            model_input_tokens_used=0,
            model_output_tokens_used=0,
            version=1,
        )
        await self.events.record(
            incident,
            "investigation.run_created",
            now,
            "control_plane",
            {
                "runId": str(run.id),
                "threadId": str(run.thread_id),
                "graphVersion": graph_version,
                "maxIterations": max_iterations,
                "maxModelRequests": max_model_requests,
                "version": run.version,
            },
            aggregate_type="investigation_run",
            aggregate_id=run.id,
            aggregate_version=run.version,
        )
        await commit_session(self.session)
        return run

    async def transition_run(
        self,
        *,
        run_id: UUID,
        expected_version: int,
        target: InvestigationRunStatus,
        error_code: str | None,
    ) -> InvestigationRunRecord:
        run = await self.runs.get_run(run_id, for_update=True)
        if run is None:
            raise ApplicationError(
                "INVESTIGATION_RUN_NOT_FOUND",
                "Investigation run does not exist",
                404,
            )
        if run.version != expected_version:
            raise ApplicationError(
                "INVESTIGATION_RUN_VERSION_CONFLICT",
                "Investigation run has changed; reload before retrying",
                409,
            )
        incident = await self.incidents.get(run.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        previous = run.status
        if target == InvestigationRunStatus.RUNNING:
            self._require_graph(run.graph_version, unavailable_status=409)
        try:
            run.status = transition_investigation_run(previous, target)
        except ValueError as exc:
            raise ApplicationError("INVALID_INVESTIGATION_RUN_TRANSITION", str(exc), 409) from exc
        now = datetime.now(UTC)
        if target == InvestigationRunStatus.RUNNING and run.started_at is None:
            run.started_at = now
        if target in _TERMINAL_RUN_STATUSES:
            run.completed_at = now
        if target in _TERMINAL_RUN_STATUSES or target == InvestigationRunStatus.PAUSED:
            run.runtime_owner = None
            run.runtime_lease_expires_at = None
        if target == InvestigationRunStatus.CANCELLED:
            for hitl_wait in await self.runs.waiting_hitl_waits_for_run(run.id):
                hitl_wait.status = InvestigationHITLWaitStatus.CANCELLED
                hitl_wait.outcome = "run_cancelled"
                hitl_wait.resolved_at = now
                hitl_wait.version += 1
                hitl_wait.updated_at = now
            for observation_wait in await self.runs.waiting_observation_waits_for_run(run.id):
                observation_wait.status = InvestigationObservationWaitStatus.CANCELLED
                observation_wait.outcome = "run_cancelled"
                observation_wait.resolved_at = now
                observation_wait.version += 1
                observation_wait.updated_at = now
                task = await self.runner_tasks.get(
                    observation_wait.runner_task_id, for_update=True
                )
                if task is not None and task.status in {
                    RunnerTaskStatus.QUEUED,
                    RunnerTaskStatus.LEASED,
                }:
                    task.status = RunnerTaskStatus.CANCELLED
                    task.lease_expires_at = None
                    task.task_fencing_token = None
                    task.error_code = "INVESTIGATION_RUN_CANCELLED"
                    task.result_summary = "Runner task cancelled with its InvestigationRun"
                    task.completed_at = now
                    task.updated_at = now
        run.last_error_code = error_code
        run.version += 1
        run.updated_at = now
        await self.events.record(
            incident,
            "investigation.status_changed",
            now,
            "agent_runtime",
            {
                "runId": str(run.id),
                "from": previous.value,
                "to": target.value,
                "errorCode": error_code,
                "version": run.version,
            },
            aggregate_type="investigation_run",
            aggregate_id=run.id,
            aggregate_version=run.version,
        )
        await commit_session(self.session)
        return run

    async def claim_next_runtime_run(
        self,
        *,
        owner: str,
        lease_seconds: int,
    ) -> InvestigationRunRecord | None:
        now = datetime.now(UTC)
        claimed = await self.runs.claim_runtime_candidate(
            owner=owner,
            now=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        if claimed is None:
            return None
        run, previous = claimed
        resumed_wait = await self.runs.latest_resolved_hitl_wait(run.id)
        if resumed_wait is not None and resumed_wait.resumed_at is None:
            resumed_wait.resumed_at = now
            resumed_wait.version += 1
            resumed_wait.updated_at = now
        resumed_observation = await self.runs.latest_resolved_observation_wait(run.id)
        if resumed_observation is not None and resumed_observation.resumed_at is None:
            resumed_observation.resumed_at = now
            resumed_observation.version += 1
            resumed_observation.updated_at = now
        incident = await self.incidents.get(run.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        event_type = (
            "investigation.status_changed"
            if previous == InvestigationRunStatus.QUEUED
            else "investigation.runtime_recovered"
        )
        payload: dict[str, object] = {
            "runId": str(run.id),
            "runtimeAttempt": run.runtime_attempt,
            "version": run.version,
        }
        if previous == InvestigationRunStatus.QUEUED:
            payload.update({"from": "queued", "to": "running", "errorCode": None})
        await self.events.record(
            incident,
            event_type,
            now,
            "agent_runtime",
            payload,
            aggregate_type="investigation_run",
            aggregate_id=run.id,
            aggregate_version=run.version,
        )
        await commit_session(self.session)
        return run

    async def write_checkpoint(
        self,
        *,
        run_id: UUID,
        node_execution_id: str,
        expected_run_version: int,
        node: str,
        iteration: int,
        plan_step_id: UUID | None,
        hypothesis_ids: list[UUID],
        evidence_ids: list[UUID],
        completed_node_keys: list[str],
        no_progress_count: int,
        progressed: bool,
        next_action: str | None,
        model_requests: int,
        model_input_tokens: int,
        model_output_tokens: int,
        output_summary: str | None,
        commit: bool = True,
    ) -> CheckpointWriteResult:
        existing = await self.runs.get_checkpoint_by_node_execution(
            run_id,
            node_execution_id,
        )
        if existing is not None:
            self._ensure_checkpoint_matches(
                existing,
                node,
                iteration,
                plan_step_id,
                hypothesis_ids,
                evidence_ids,
                completed_node_keys,
                no_progress_count,
                progressed,
                next_action,
                model_requests,
                model_input_tokens,
                model_output_tokens,
                output_summary,
            )
            run = await self.runs.get_run(run_id)
            if run is None:
                raise ApplicationError(
                    "INVESTIGATION_RUN_NOT_FOUND",
                    "Investigation run does not exist",
                    404,
                )
            return CheckpointWriteResult(existing, run.version, True)

        run = await self.runs.get_run(run_id, for_update=True)
        if run is None:
            raise ApplicationError(
                "INVESTIGATION_RUN_NOT_FOUND",
                "Investigation run does not exist",
                404,
            )
        concurrent_existing = await self.runs.get_checkpoint_by_node_execution(
            run_id,
            node_execution_id,
        )
        if concurrent_existing is not None:
            self._ensure_checkpoint_matches(
                concurrent_existing,
                node,
                iteration,
                plan_step_id,
                hypothesis_ids,
                evidence_ids,
                completed_node_keys,
                no_progress_count,
                progressed,
                next_action,
                model_requests,
                model_input_tokens,
                model_output_tokens,
                output_summary,
            )
            return CheckpointWriteResult(concurrent_existing, run.version, True)
        if run.version != expected_run_version:
            raise ApplicationError(
                "INVESTIGATION_RUN_VERSION_CONFLICT",
                "Investigation run has changed; reload before retrying",
                409,
            )
        if run.status != InvestigationRunStatus.RUNNING:
            raise ApplicationError(
                "INVESTIGATION_RUN_NOT_RUNNING",
                "Checkpoints can only be written while the run is running",
                409,
            )
        graph = self._require_graph(run.graph_version, unavailable_status=409)
        if node not in graph.node_keys:
            raise ApplicationError(
                "INVESTIGATION_GRAPH_NODE_NOT_FOUND",
                f"Node '{node}' is not registered in graph '{run.graph_version}'",
                422,
            )
        if iteration < run.iteration_count or iteration > run.max_iterations:
            raise ApplicationError(
                "INVALID_INVESTIGATION_ITERATION",
                "Checkpoint iteration must be monotonic and within the run limit",
                409,
            )
        if len(set(completed_node_keys)) != len(completed_node_keys):
            raise ApplicationError(
                "DUPLICATE_COMPLETED_NODE_KEY",
                "Completed node keys must be unique",
                422,
            )
        self._validate_completed_node_keys(graph.node_keys, completed_node_keys)
        if no_progress_count > iteration + 1:
            raise ApplicationError(
                "INVALID_NO_PROGRESS_COUNT",
                "No-progress count cannot exceed the number of attempted iterations",
                422,
            )
        await self._validate_checkpoint_references(
            run.incident_id,
            plan_step_id,
            hypothesis_ids,
            evidence_ids,
        )
        if run.model_requests_used + model_requests > run.model_request_limit:
            raise ApplicationError(
                "MODEL_REQUEST_BUDGET_EXHAUSTED",
                "Investigation run model-request budget is exhausted",
                409,
            )
        incident = await self.incidents.get(run.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)

        now = datetime.now(UTC)
        sequence = run.last_checkpoint_sequence + 1
        checkpoint = await self.runs.create_checkpoint(
            run_id=run.id,
            sequence=sequence,
            node_execution_id=node_execution_id,
            node=node,
            graph_version=run.graph_version,
            iteration=iteration,
            plan_step_id=plan_step_id,
            hypothesis_ids=[str(item) for item in hypothesis_ids],
            evidence_ids=[str(item) for item in evidence_ids],
            completed_node_keys=completed_node_keys,
            no_progress_count=no_progress_count,
            progressed=progressed,
            next_action=next_action,
            model_requests=model_requests,
            model_input_tokens=model_input_tokens,
            model_output_tokens=model_output_tokens,
            output_summary=output_summary,
            created_at=now,
        )
        run.current_node = node
        run.iteration_count = iteration
        run.last_checkpoint_sequence = sequence
        run.model_requests_used += model_requests
        run.model_input_tokens_used += model_input_tokens
        run.model_output_tokens_used += model_output_tokens
        run.version += 1
        run.updated_at = now
        await self.events.record(
            incident,
            "investigation.checkpointed",
            now,
            "agent_runtime",
            {
                "runId": str(run.id),
                "checkpointId": str(checkpoint.id),
                "sequence": sequence,
                "node": node,
                "iteration": iteration,
                "version": run.version,
            },
            aggregate_type="investigation_run",
            aggregate_id=run.id,
            aggregate_version=run.version,
        )
        if commit:
            await commit_session(self.session)
        return CheckpointWriteResult(checkpoint, run.version, False)

    async def get_run(self, run_id: UUID) -> InvestigationRunRecord:
        run = await self.runs.get_run(run_id)
        if run is None:
            raise ApplicationError(
                "INVESTIGATION_RUN_NOT_FOUND",
                "Investigation run does not exist",
                404,
            )
        return run

    async def list_runs(
        self,
        incident_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[InvestigationRunRecord], int]:
        if await self.incidents.get(incident_id) is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        runs = await self.runs.list_runs_for_incident(incident_id, limit, offset)
        total = await self.runs.count_runs_for_incident(incident_id)
        return runs, total

    async def list_checkpoints(
        self,
        run_id: UUID,
        after_sequence: int,
        limit: int,
    ) -> list[InvestigationCheckpointRecord]:
        await self.get_run(run_id)
        return await self.runs.list_checkpoints(run_id, after_sequence, limit)

    async def _validate_checkpoint_references(
        self,
        incident_id: UUID,
        plan_step_id: UUID | None,
        hypothesis_ids: list[UUID],
        evidence_ids: list[UUID],
    ) -> None:
        if plan_step_id is not None:
            step = await self.plans.get_step_for_incident(incident_id, plan_step_id)
            if step is None:
                raise ApplicationError(
                    "CHECKPOINT_PLAN_STEP_NOT_FOUND",
                    "Checkpoint PlanStep must belong to the Incident",
                    422,
                )
        hypothesis_set = set(hypothesis_ids)
        if (
            await self.hypotheses.existing_ids_for_incident(
                incident_id,
                hypothesis_set,
            )
            != hypothesis_set
        ):
            raise ApplicationError(
                "CHECKPOINT_HYPOTHESIS_NOT_FOUND",
                "All checkpoint Hypotheses must belong to the Incident",
                422,
            )
        evidence_set = set(evidence_ids)
        if (
            await self.evidence.existing_ids_for_incident(
                incident_id,
                evidence_set,
            )
            != evidence_set
        ):
            raise ApplicationError(
                "CHECKPOINT_EVIDENCE_NOT_FOUND",
                "All checkpoint Evidence must belong to the Incident",
                422,
            )

    @staticmethod
    def _ensure_checkpoint_matches(
        existing: InvestigationCheckpointRecord,
        node: str,
        iteration: int,
        plan_step_id: UUID | None,
        hypothesis_ids: list[UUID],
        evidence_ids: list[UUID],
        completed_node_keys: list[str],
        no_progress_count: int,
        progressed: bool,
        next_action: str | None,
        model_requests: int,
        model_input_tokens: int,
        model_output_tokens: int,
        output_summary: str | None,
    ) -> None:
        matches = (
            existing.node == node
            and existing.iteration == iteration
            and existing.plan_step_id == plan_step_id
            and existing.hypothesis_ids == [str(item) for item in hypothesis_ids]
            and existing.evidence_ids == [str(item) for item in evidence_ids]
            and existing.completed_node_keys == completed_node_keys
            and existing.no_progress_count == no_progress_count
            and existing.progressed == progressed
            and existing.next_action == next_action
            and existing.model_requests == model_requests
            and existing.model_input_tokens == model_input_tokens
            and existing.model_output_tokens == model_output_tokens
            and existing.output_summary == output_summary
        )
        if not matches:
            raise ApplicationError(
                "CHECKPOINT_IDEMPOTENCY_CONFLICT",
                "Node execution ID is already used by a different checkpoint",
                409,
            )

    @staticmethod
    def _require_graph(
        graph_version: str,
        unavailable_status: int,
    ) -> InvestigationGraphDefinition:
        graph = get_investigation_graph(graph_version)
        if graph is None:
            raise ApplicationError(
                "INVESTIGATION_GRAPH_VERSION_UNAVAILABLE",
                f"Investigation graph version '{graph_version}' is not available",
                unavailable_status,
            )
        return graph

    @staticmethod
    def _validate_completed_node_keys(
        registered_nodes: frozenset[str],
        completed_node_keys: list[str],
    ) -> None:
        for completed_key in completed_node_keys:
            node, separator, iteration = completed_key.rpartition(":")
            if not separator or node not in registered_nodes or not iteration.isdecimal():
                raise ApplicationError(
                    "INVALID_COMPLETED_NODE_KEY",
                    "Completed node keys must use a registered '<node>:<iteration>' value",
                    422,
                )
