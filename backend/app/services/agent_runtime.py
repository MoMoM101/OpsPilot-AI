import asyncio
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, ClassVar, Literal, Protocol, TypedDict, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from app.core.logging import get_logger
from app.core.worker_health import WorkerHealthRegistry
from app.domain.investigations import (
    InvestigationHITLSubjectType,
    InvestigationRunStatus,
    get_investigation_graph,
)
from app.domain.runner_tasks import RunnerReadOperation
from app.services.agent_provider import AgentProviderBudgetExceeded, AgentProviderError
from app.services.investigation_hitl import InvestigationHITLService
from app.services.investigations import InvestigationService
from app.storage.database import Database
from app.storage.repositories import InvestigationRepository

logger = get_logger(__name__)

RuntimeAction = Literal["continue", "finish", "pause"]


@dataclass(frozen=True, slots=True)
class AgentNodeContext:
    run_id: UUID
    node: str
    node_execution_id: str
    iteration: int
    requested_action: str | None
    hitl_wait_id: UUID | None = None
    hitl_subject_type: str | None = None
    hitl_subject_id: UUID | None = None
    hitl_outcome: str | None = None


@dataclass(frozen=True, slots=True)
class AgentNodeOutcome:
    summary: str
    progressed: bool = True
    next_action: RuntimeAction | None = None
    plan_step_id: UUID | None = None
    hypothesis_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    model_requests: int = 0
    model_input_tokens: int = 0
    model_output_tokens: int = 0
    hitl_subject_type: str | None = None
    hitl_subject_id: UUID | None = None
    observation_resource_id: UUID | None = None
    observation_operation: RunnerReadOperation | None = None
    observation_purpose: str | None = None


class AgentNodeHandler(Protocol):
    async def execute(self, context: AgentNodeContext) -> AgentNodeOutcome: ...


class RuntimeState(TypedDict):
    run_id: str
    iteration: int
    max_iterations: int
    completed_node_keys: list[str]
    no_progress_count: int
    next_action: str | None
    hitl_wait_id: str | None
    hitl_subject_type: str | None
    hitl_subject_id: str | None
    hitl_outcome: str | None


class AgentNodeHandlerUnavailable(RuntimeError):
    pass


class RuntimeLeaseLost(RuntimeError):
    pass


class RuntimeGraphUnavailable(RuntimeError):
    pass


class UnavailableAgentNodeHandler:
    async def execute(self, context: AgentNodeContext) -> AgentNodeOutcome:
        raise AgentNodeHandlerUnavailable(
            f"No Agent node provider is configured for '{context.node}'"
        )


class AgentGraphExecutor:
    _CONTEXT_NODES: ClassVar[frozenset[str]] = frozenset(
        {
            "load_incident",
            "load_topology",
            "load_recent_changes",
            "classify_complexity",
            "create_plan",
        }
    )

    def __init__(
        self,
        database: Database,
        handler: AgentNodeHandler,
        *,
        owner: str,
        lease_seconds: int,
        no_progress_limit: int,
        runner_lease_seconds: int,
        runner_task_lease_seconds: int,
        runner_task_max_output_bytes: int,
    ) -> None:
        self.database = database
        self.handler = handler
        self.owner = owner
        self.lease_seconds = lease_seconds
        self.no_progress_limit = no_progress_limit
        self.runner_lease_seconds = runner_lease_seconds
        self.runner_task_lease_seconds = runner_task_lease_seconds
        self.runner_task_max_output_bytes = runner_task_max_output_bytes
        self.graphs: dict[str, Any] = {
            version: self._build_graph(version) for version in ("graph-v1", "graph-v2")
        }

    def _build_graph(self, graph_version: str) -> Any:
        builder = StateGraph(RuntimeState)
        definition = get_investigation_graph(graph_version)
        if definition is None:
            raise RuntimeError(
                f"{graph_version} must remain registered while its runtime is installed"
            )
        for node in definition.nodes:
            builder.add_node(node.key, self._node_callback(node.key))
        ordered = [node.key for node in definition.nodes]
        replan_index = ordered.index("maybe_replan")
        builder.add_edge(START, ordered[0])
        for current, following in pairwise(ordered[: replan_index + 1]):
            if current in {"run_investigator", "propose_action"}:
                builder.add_conditional_edges(
                    current,
                    self._route_after_interrupt,
                    {"continue": following, "stop": END},
                )
            else:
                builder.add_edge(current, following)
        builder.add_conditional_edges(
            "maybe_replan",
            self._route_after_replan,
            {
                "continue": "select_next_step",
                "finish": "escalate_or_finish",
                "stop": END,
            },
        )
        builder.add_edge("escalate_or_finish", END)
        return builder.compile()

    def _node_callback(self, node: str):  # type: ignore[no-untyped-def]
        async def execute(state: RuntimeState) -> dict[str, object]:
            iteration = 0 if node in self._CONTEXT_NODES else state["iteration"]
            completed_key = f"{node}:{iteration}"
            if completed_key in state["completed_node_keys"]:
                update: dict[str, object] = {}
                if node == "maybe_replan" and state["next_action"] == "continue":
                    update["iteration"] = iteration + 1
                return update

            run_id = UUID(state["run_id"])
            execution_id = f"{run_id}:{node}:{iteration}"
            await self._renew_lease(run_id)
            outcome = await self.handler.execute(
                AgentNodeContext(
                    run_id=run_id,
                    node=node,
                    node_execution_id=execution_id,
                    iteration=iteration,
                    requested_action=state["next_action"],
                    hitl_wait_id=(UUID(state["hitl_wait_id"]) if state["hitl_wait_id"] else None),
                    hitl_subject_type=state["hitl_subject_type"],
                    hitl_subject_id=(
                        UUID(state["hitl_subject_id"]) if state["hitl_subject_id"] else None
                    ),
                    hitl_outcome=state["hitl_outcome"],
                )
            )
            no_progress = state["no_progress_count"]
            if node == "maybe_replan":
                no_progress = 0 if outcome.progressed else no_progress + 1
            next_action: str | None = outcome.next_action or state["next_action"]
            if node == "maybe_replan" and no_progress >= self.no_progress_limit:
                next_action = "no_progress"
            elif (
                node == "maybe_replan"
                and next_action == "continue"
                and iteration + 1 >= state["max_iterations"]
            ):
                next_action = "max_iterations"
            completed = [*state["completed_node_keys"], completed_key]
            await self._write_checkpoint(
                run_id=run_id,
                execution_id=execution_id,
                node=node,
                iteration=iteration,
                completed=completed,
                no_progress=no_progress,
                outcome=outcome,
                next_action=next_action,
            )
            update = {
                "completed_node_keys": completed,
                "no_progress_count": no_progress,
                "next_action": next_action,
            }
            if node == "maybe_replan" and next_action == "continue":
                update["iteration"] = iteration + 1
            return update

        return execute

    @staticmethod
    def _route_after_replan(state: RuntimeState) -> str:
        if state["next_action"] == "continue":
            return "continue"
        if state["next_action"] in {"pause", "no_progress", "max_iterations"}:
            return "stop"
        return "finish"

    @staticmethod
    def _route_after_interrupt(state: RuntimeState) -> str:
        return "stop" if state["next_action"] == "pause" else "continue"

    async def execute(self, run_id: UUID) -> RuntimeState:
        async with self.database.session_factory() as session:
            runs = InvestigationRepository(session)
            run = await runs.get_run(run_id)
            if run is None:
                raise RuntimeError("Investigation run disappeared before execution")
            if run.runtime_owner != self.owner:
                raise RuntimeLeaseLost("Investigation run is owned by another runtime")
            if get_investigation_graph(run.graph_version) is None:
                raise RuntimeGraphUnavailable(
                    f"No runtime executor is installed for '{run.graph_version}'"
                )
            latest = await runs.get_latest_checkpoint(run_id)
            resolved_wait = await runs.latest_resolved_hitl_wait(run_id)
            resolved_observation = await runs.latest_resolved_observation_wait(run_id)
            initial = RuntimeState(
                run_id=str(run.id),
                iteration=latest.iteration if latest else 0,
                max_iterations=run.max_iterations,
                completed_node_keys=latest.completed_node_keys if latest else [],
                no_progress_count=latest.no_progress_count if latest else 0,
                next_action=(
                    None
                    if resolved_wait is not None or resolved_observation is not None
                    else latest.next_action if latest else None
                ),
                hitl_wait_id=str(resolved_wait.id) if resolved_wait else None,
                hitl_subject_type=(resolved_wait.subject_type.value if resolved_wait else None),
                hitl_subject_id=str(resolved_wait.subject_id) if resolved_wait else None,
                hitl_outcome=resolved_wait.outcome if resolved_wait else None,
            )
        result = await self.graphs[run.graph_version].ainvoke(
            initial, config={"recursion_limit": 1000}
        )
        return cast(RuntimeState, result)

    async def _renew_lease(self, run_id: UUID) -> None:
        from datetime import UTC, datetime, timedelta

        async with self.database.session_factory() as session:
            renewed = await InvestigationRepository(session).renew_runtime_lease(
                run_id,
                self.owner,
                datetime.now(UTC) + timedelta(seconds=self.lease_seconds),
            )
            if not renewed:
                raise RuntimeLeaseLost("Investigation runtime lease was lost")
            await session.commit()

    async def _write_checkpoint(
        self,
        *,
        run_id: UUID,
        execution_id: str,
        node: str,
        iteration: int,
        completed: list[str],
        no_progress: int,
        outcome: AgentNodeOutcome,
        next_action: str | None,
    ) -> None:
        async with self.database.session_factory() as session:
            runs = InvestigationRepository(session)
            run = await runs.get_run(run_id)
            if run is None or run.runtime_owner != self.owner:
                raise RuntimeLeaseLost("Investigation runtime lease was lost before checkpoint")
            checkpoint_result = await InvestigationService(session).write_checkpoint(
                run_id=run_id,
                node_execution_id=execution_id,
                expected_run_version=run.version,
                node=node,
                iteration=iteration,
                plan_step_id=outcome.plan_step_id,
                hypothesis_ids=list(outcome.hypothesis_ids),
                evidence_ids=list(outcome.evidence_ids),
                completed_node_keys=completed,
                no_progress_count=no_progress,
                progressed=outcome.progressed,
                next_action=next_action,
                model_requests=outcome.model_requests,
                model_input_tokens=outcome.model_input_tokens,
                model_output_tokens=outcome.model_output_tokens,
                output_summary=outcome.summary,
                commit=(
                    outcome.hitl_subject_id is None
                    and outcome.observation_operation is None
                ),
            )
            if outcome.hitl_subject_id is not None:
                if outcome.hitl_subject_type is None:
                    raise RuntimeError("HITL subject type is required")
                run = await runs.get_run(run_id)
                checkpoint = await runs.get_checkpoint_by_node_execution(run_id, execution_id)
                if run is None or checkpoint is None:
                    raise RuntimeError("Checkpoint disappeared before HITL interrupt")
                await InvestigationHITLService(session).start_wait(
                    run_id=run_id,
                    checkpoint_id=checkpoint.id,
                    subject_type=InvestigationHITLSubjectType(outcome.hitl_subject_type),
                    subject_id=outcome.hitl_subject_id,
                    expected_run_version=run.version,
                )
            elif outcome.observation_operation is not None:
                if (
                    outcome.observation_resource_id is None
                    or outcome.observation_purpose is None
                    or outcome.plan_step_id is None
                ):
                    raise RuntimeError("Observation Resource, purpose and PlanStep are required")
                from app.services.investigation_observations import (
                    InvestigationObservationService,
                )

                run = await runs.get_run(run_id)
                if run is None:
                    raise RuntimeError("Investigation run disappeared before Observation wait")
                await InvestigationObservationService(
                    session,
                    runner_lease_seconds=self.runner_lease_seconds,
                    task_lease_seconds=self.runner_task_lease_seconds,
                    max_output_bytes=self.runner_task_max_output_bytes,
                ).start_wait(
                    run_id=run_id,
                    checkpoint=checkpoint_result.checkpoint,
                    node_execution_id=execution_id,
                    expected_run_version=run.version,
                    plan_step_id=outcome.plan_step_id,
                    resource_id=outcome.observation_resource_id,
                    operation=outcome.observation_operation,
                    purpose=outcome.observation_purpose,
                    model_requests=outcome.model_requests,
                    model_input_tokens=outcome.model_input_tokens,
                    model_output_tokens=outcome.model_output_tokens,
                    output_summary=outcome.summary,
                )


class AgentRuntimeWorker:
    def __init__(
        self,
        database: Database,
        handler: AgentNodeHandler,
        *,
        owner: str | None = None,
        lease_seconds: int = 60,
        no_progress_limit: int = 3,
        runner_lease_seconds: int = 60,
        runner_task_lease_seconds: int = 120,
        runner_task_max_output_bytes: int = 65536,
    ) -> None:
        self.database = database
        self.owner = owner or f"control-plane-{uuid4()}"
        self.lease_seconds = lease_seconds
        self.executor = AgentGraphExecutor(
            database,
            handler,
            owner=self.owner,
            lease_seconds=lease_seconds,
            no_progress_limit=no_progress_limit,
            runner_lease_seconds=runner_lease_seconds,
            runner_task_lease_seconds=runner_task_lease_seconds,
            runner_task_max_output_bytes=runner_task_max_output_bytes,
        )

    async def run_once(self) -> bool:
        async with self.database.session_factory() as session:
            run = await InvestigationService(session).claim_next_runtime_run(
                owner=self.owner,
                lease_seconds=self.lease_seconds,
            )
        if run is None:
            return False
        try:
            state = await self.executor.execute(run.id)
            if state["next_action"] in {"pause", "no_progress", "max_iterations"}:
                await self._finish(run.id, InvestigationRunStatus.PAUSED, None)
            else:
                await self._finish(run.id, InvestigationRunStatus.COMPLETED, None)
        except RuntimeLeaseLost:
            logger.warning("agent_runtime_lease_lost", run_id=str(run.id), owner=self.owner)
        except AgentNodeHandlerUnavailable:
            await self._finish(
                run.id,
                InvestigationRunStatus.FAILED,
                "AGENT_NODE_HANDLER_UNAVAILABLE",
            )
        except RuntimeGraphUnavailable:
            await self._finish(
                run.id,
                InvestigationRunStatus.FAILED,
                "INVESTIGATION_GRAPH_VERSION_UNAVAILABLE",
            )
        except AgentProviderBudgetExceeded:
            await self._finish(
                run.id,
                InvestigationRunStatus.FAILED,
                "MODEL_REQUEST_BUDGET_EXHAUSTED",
            )
        except AgentProviderError:
            await self._finish(
                run.id,
                InvestigationRunStatus.FAILED,
                "AGENT_MODEL_PROVIDER_ERROR",
            )
        except Exception as exc:
            logger.exception(
                "agent_runtime_execution_failed",
                run_id=str(run.id),
                error_type=type(exc).__name__,
            )
            await self._finish(run.id, InvestigationRunStatus.FAILED, "AGENT_RUNTIME_ERROR")
        return True

    async def _finish(
        self,
        run_id: UUID,
        target: InvestigationRunStatus,
        error_code: str | None,
    ) -> None:
        async with self.database.session_factory() as session:
            service = InvestigationService(session)
            run = await service.get_run(run_id)
            if run.status == target and run.runtime_owner is None:
                return
            if run.runtime_owner != self.owner:
                raise RuntimeLeaseLost("Cannot finish a run owned by another runtime")
            await service.transition_run(
                run_id=run_id,
                expected_version=run.version,
                target=target,
                error_code=error_code,
            )


async def run_agent_runtime(
    worker: AgentRuntimeWorker,
    poll_interval_seconds: float,
    health: WorkerHealthRegistry | None = None,
) -> None:
    worker_name = "agent_runtime"
    while True:
        try:
            processed = (
                await health.run_monitored(worker_name, worker.run_once())
                if health is not None
                else await worker.run_once()
            )
            if health is not None:
                health.success(worker_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if health is not None:
                health.failure(worker_name, exc)
            logger.error("agent_runtime_worker_failed", error_type=type(exc).__name__)
            processed = False
        if not processed:
            await asyncio.sleep(poll_interval_seconds)
