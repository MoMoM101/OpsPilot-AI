import json
from typing import Any
from uuid import UUID

from app.domain.actions import ActionProposalStatus
from app.domain.plans import PlanStatus, PlanStepStatus, PlanStepType
from app.domain.runner_tasks import RunnerReadOperation
from app.services.action_proposals import ActionProposalInput, ActionProposalService
from app.services.agent_prompt_security import (
    build_agent_context,
    validate_evidence_references,
)
from app.services.agent_provider import (
    AgentProvider,
    AgentProviderBudgetExceeded,
    ProviderResult,
)
from app.services.agent_runtime import AgentNodeContext, AgentNodeOutcome, RuntimeAction
from app.services.hypotheses import HypothesisService
from app.services.plans import PlanService, PlanStepInput
from app.storage.database import Database
from app.storage.repositories import (
    EvidenceRepository,
    IncidentRepository,
    InvestigationRepository,
    PlanRepository,
)


class ProviderBackedAgentNodeHandler:
    def __init__(self, database: Database, provider: AgentProvider) -> None:
        self.database = database
        self.provider = provider

    async def execute(self, context: AgentNodeContext) -> AgentNodeOutcome:
        if context.node == "create_plan":
            return await self._create_plan(context)
        if context.node == "select_next_step":
            return await self._select_next_step(context)
        if context.node == "run_investigator":
            return await self._run_investigator(context)
        if context.node == "assess_evidence":
            return await self._assess_evidence(context)
        if context.node == "maybe_replan":
            return await self._replan(context)
        if context.node == "propose_action":
            return await self._propose_action(context)
        summaries = {
            "load_incident": "Loaded sanitized Incident fields",
            "load_topology": "Loaded bounded resource scope",
            "load_recent_changes": "Loaded available recent-change references",
            "classify_complexity": "Selected the standard bounded investigation route",
            "escalate_or_finish": "Investigation route reached its terminal decision",
        }
        return AgentNodeOutcome(summaries[context.node])

    async def _context(self, run_id: UUID) -> tuple[UUID, dict[str, object], int, set[UUID]]:
        async with self.database.session_factory() as session:
            run = await InvestigationRepository(session).get_run(run_id)
            if run is None:
                raise RuntimeError("Investigation run does not exist")
            incident = await IncidentRepository(session).get(run.incident_id)
            if incident is None:
                raise RuntimeError("Incident does not exist")
            evidence = await EvidenceRepository(session).list_for_incident(
                incident.id, 50, 0, None, None
            )
            payload, allowed_evidence_ids = build_agent_context(incident, evidence)
            remaining = run.model_request_limit - run.model_requests_used
            return incident.id, payload, remaining, allowed_evidence_ids

    async def _create_plan(self, context: AgentNodeContext) -> AgentNodeOutcome:
        incident_id, payload, remaining, _ = await self._context(context.run_id)
        if remaining <= 0:
            raise AgentProviderBudgetExceeded("Model request budget is exhausted")
        result = await self.provider.plan(
            json.dumps(payload, ensure_ascii=False), request_limit=remaining
        )
        output = result.output
        incident_resource_id = payload["incident"]["resourceId"]  # type: ignore[index]
        out_of_scope = any(
            str(scope) != incident_resource_id
            for step in output.steps
            for scope in step.resource_scope
        )
        if out_of_scope:
            raise RuntimeError("Planner returned a resource outside the Incident scope")
        steps = [
            PlanStepInput(
                title=item.title,
                objective=item.objective,
                step_type=item.kind,
                dependencies=[str(value) for value in item.dependencies],
                resource_scope=[str(value) for value in item.resource_scope],
                allowed_capabilities=item.allowed_capabilities,
                expected_evidence=item.expected_evidence,
                success_criteria=item.success_criteria,
                risk=item.risk,
            )
            for item in output.steps
        ]
        async with self.database.session_factory() as session:
            await PlanService(session).create(
                incident_id,
                output.objective,
                output.max_tool_calls,
                output.max_duration_seconds,
                steps,
            )
        return self._outcome(result, output.summary)

    async def _select_next_step(self, context: AgentNodeContext) -> AgentNodeOutcome:
        incident_id, _, _, _ = await self._context(context.run_id)
        async with self.database.session_factory() as session:
            plans = PlanRepository(session)
            plan = await plans.get_latest(incident_id)
            if plan is None or plan.status != PlanStatus.ACTIVE:
                return AgentNodeOutcome("No active plan remains", next_action="finish")
            steps = await plans.list_steps(plan.id)
            completed = {
                item.ordinal
                for item in steps
                if item.status in {PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED}
            }
            step = next(
                (
                    item
                    for item in steps
                    if item.status == PlanStepStatus.PENDING
                    and all(int(value) in completed for value in item.dependencies)
                ),
                None,
            )
            if step is None:
                return AgentNodeOutcome("No runnable plan step remains", next_action="finish")
            step_id, version = step.id, step.version
        async with self.database.session_factory() as session:
            await PlanService(session).transition_step(
                incident_id, step_id, PlanStepStatus.RUNNING, version, [], None
            )
        return AgentNodeOutcome("Selected the next runnable plan step", plan_step_id=step_id)

    async def _run_investigator(self, context: AgentNodeContext) -> AgentNodeOutcome:
        incident_id, payload, remaining, _ = await self._context(context.run_id)
        async with self.database.session_factory() as session:
            plans = PlanRepository(session)
            plan = await plans.get_latest(incident_id)
            if plan is None or plan.status != PlanStatus.ACTIVE:
                return AgentNodeOutcome("No active plan remains", next_action="finish")
            step = next(
                (
                    item
                    for item in await plans.list_steps(plan.id)
                    if item.status == PlanStepStatus.RUNNING
                    and item.step_type
                    in {
                        PlanStepType.OBSERVE,
                        PlanStepType.ANALYZE,
                        PlanStepType.EXPERIMENT,
                        PlanStepType.VERIFY,
                    }
                    and any(
                        capability in {operation.value for operation in RunnerReadOperation}
                        for capability in item.allowed_capabilities
                    )
                ),
                None,
            )
            if step is None:
                return AgentNodeOutcome("The active PlanStep does not require an observation")
            incident = await IncidentRepository(session).get(incident_id)
            if incident is None:
                raise RuntimeError("Incident does not exist")
            from app.storage.repositories import ResourceRepository

            resource = await ResourceRepository(session).get(incident.resource_id)
            if resource is None:
                raise RuntimeError("Incident Resource does not exist")
            observability = resource.attributes.get("observability")
            configured = (
                observability.get("runnerOperations", {})
                if isinstance(observability, dict)
                else {}
            )
            allowed_operations = sorted(
                operation.value
                for operation in RunnerReadOperation
                if operation.value in step.allowed_capabilities
                and isinstance(configured, dict)
                and operation.value in configured
            )
            step_id = step.id
            resource_id = resource.id
        if not allowed_operations:
            raise RuntimeError("No trusted Runner operation is configured for the PlanStep")
        payload["activePlanStep"] = {
            "id": str(step_id),
            "resourceIds": [str(resource_id)],
            "allowedOperations": allowed_operations,
        }
        if remaining <= 0:
            raise AgentProviderBudgetExceeded("Model request budget is exhausted")
        result = await self.provider.observe(
            json.dumps(payload, ensure_ascii=False), request_limit=remaining
        )
        output = result.output
        if output.action != "observe" or output.proposal is None:
            return self._outcome(
                result,
                output.reason,
                progressed=False,
                next_action="pause" if output.action == "escalate" else None,
                plan_step_id=step_id,
            )
        if output.proposal.resource_id != resource_id:
            raise RuntimeError("Observer returned a Resource outside the Incident scope")
        if output.proposal.operation.value not in allowed_operations:
            raise RuntimeError("Observer returned an Operation outside the PlanStep allowlist")
        return self._outcome(
            result,
            output.reason,
            next_action="pause",
            plan_step_id=step_id,
            observation_resource_id=resource_id,
            observation_operation=output.proposal.operation,
            observation_purpose=output.proposal.purpose,
        )

    async def _assess_evidence(self, context: AgentNodeContext) -> AgentNodeOutcome:
        incident_id, payload, remaining, allowed_evidence_ids = await self._context(context.run_id)
        if remaining <= 0:
            raise AgentProviderBudgetExceeded("Model request budget is exhausted")
        result = await self.provider.investigate(
            json.dumps(payload, ensure_ascii=False), request_limit=remaining
        )
        referenced_evidence_ids = [*result.output.evidence_ids]
        for proposal in result.output.hypotheses:
            referenced_evidence_ids.extend(proposal.supporting_evidence_ids)
            referenced_evidence_ids.extend(proposal.contradicting_evidence_ids)
        validate_evidence_references(referenced_evidence_ids, allowed_evidence_ids)
        created: list[UUID] = []
        for proposal in result.output.hypotheses:
            async with self.database.session_factory() as session:
                record = await HypothesisService(session).create(
                    incident_id=incident_id,
                    summary=proposal.summary,
                    confidence=proposal.confidence,
                    supporting_evidence_ids=proposal.supporting_evidence_ids,
                    contradicting_evidence_ids=proposal.contradicting_evidence_ids,
                )
                created.append(record.id)
        return self._outcome(
            result,
            result.output.summary,
            progressed=result.output.progressed,
            hypothesis_ids=tuple(created),
            evidence_ids=tuple(result.output.evidence_ids),
        )

    async def _replan(self, context: AgentNodeContext) -> AgentNodeOutcome:
        _, payload, remaining, _ = await self._context(context.run_id)
        if context.hitl_wait_id is not None:
            payload["hitlDecision"] = {
                "waitId": str(context.hitl_wait_id),
                "subjectType": context.hitl_subject_type,
                "subjectId": (str(context.hitl_subject_id) if context.hitl_subject_id else None),
                "outcome": context.hitl_outcome,
            }
        if remaining <= 0:
            raise AgentProviderBudgetExceeded("Model request budget is exhausted")
        result = await self.provider.replan(
            json.dumps(payload, ensure_ascii=False), request_limit=remaining
        )
        return self._outcome(
            result,
            result.output.reason,
            progressed=result.output.progressed,
            next_action=result.output.action,
        )

    async def _propose_action(self, context: AgentNodeContext) -> AgentNodeOutcome:
        _, payload, remaining, _ = await self._context(context.run_id)
        if remaining <= 0:
            raise AgentProviderBudgetExceeded("Model request budget is exhausted")
        result = await self.provider.propose_action(
            json.dumps(payload, ensure_ascii=False), request_limit=remaining
        )
        output = result.output
        if output.action != "propose" or output.proposal is None:
            return self._outcome(
                result,
                output.reason,
                progressed=False,
                next_action="pause" if output.action == "escalate" else None,
            )
        proposal_input = ActionProposalInput(
            resource_id=output.proposal.resource_id,
            capability=output.proposal.capability,
            parameters=dict(output.proposal.parameters),
            verification_criteria=output.proposal.verification_criteria,
            rollback_capability=output.proposal.rollback_capability,
            risk=output.proposal.risk,
        )
        async with self.database.session_factory() as session:
            proposal = (
                await ActionProposalService(session).propose(
                    run_id=context.run_id,
                    node_execution_id=context.node_execution_id,
                    input=proposal_input,
                )
            ).proposal
        if proposal.status == ActionProposalStatus.AWAITING_APPROVAL:
            return self._outcome(
                result,
                output.reason,
                next_action="pause",
                plan_step_id=proposal.plan_step_id,
                hitl_subject_type="approval",
                hitl_subject_id=proposal.approval_id,
            )
        if proposal.status == ActionProposalStatus.DENIED:
            return self._outcome(
                result,
                proposal.decision_reason or output.reason,
                next_action="pause",
                plan_step_id=proposal.plan_step_id,
            )
        return self._outcome(result, output.reason, plan_step_id=proposal.plan_step_id)

    @staticmethod
    def _outcome(
        result: ProviderResult[Any],
        summary: str,
        *,
        progressed: bool = True,
        next_action: RuntimeAction | None = None,
        hypothesis_ids: tuple[UUID, ...] = (),
        evidence_ids: tuple[UUID, ...] = (),
        plan_step_id: UUID | None = None,
        hitl_subject_type: str | None = None,
        hitl_subject_id: UUID | None = None,
        observation_resource_id: UUID | None = None,
        observation_operation: RunnerReadOperation | None = None,
        observation_purpose: str | None = None,
    ) -> AgentNodeOutcome:
        return AgentNodeOutcome(
            summary,
            progressed=progressed,
            next_action=next_action,
            hypothesis_ids=hypothesis_ids,
            evidence_ids=evidence_ids,
            plan_step_id=plan_step_id,
            model_requests=result.requests,
            model_input_tokens=result.input_tokens,
            model_output_tokens=result.output_tokens,
            hitl_subject_type=hitl_subject_type,
            hitl_subject_id=hitl_subject_id,
            observation_resource_id=observation_resource_id,
            observation_operation=observation_operation,
            observation_purpose=observation_purpose,
        )
