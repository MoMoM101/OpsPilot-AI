from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.actions import ActionProposalStatus
from app.domain.approvals import ApprovalStatus
from app.domain.plans import PlanStepRisk, PlanStepStatus, PlanStepType
from app.domain.policies import AutonomyLevel
from app.services.actions import ActionRequestService
from app.services.events import EventRecorder
from app.services.policies import PolicyService
from app.storage.models import ActionProposalRecord, ApprovalRecord
from app.storage.repositories import (
    ActionProposalRepository,
    IncidentRepository,
    InvestigationRepository,
    PlanRepository,
    ResourceRepository,
)
from app.storage.transactions import commit_session


@dataclass(frozen=True, slots=True)
class ActionProposalInput:
    resource_id: UUID
    capability: str
    parameters: dict[str, object]
    verification_criteria: list[str]
    rollback_capability: str | None
    risk: PlanStepRisk


@dataclass(frozen=True, slots=True)
class ActionProposalResult:
    proposal: ActionProposalRecord
    duplicate: bool


class ActionProposalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.proposals = ActionProposalRepository(session)
        self.runs = InvestigationRepository(session)
        self.incidents = IncidentRepository(session)
        self.resources = ResourceRepository(session)
        self.plans = PlanRepository(session)
        self.events = EventRecorder(session)

    async def propose(
        self,
        *,
        run_id: UUID,
        node_execution_id: str,
        input: ActionProposalInput,
    ) -> ActionProposalResult:
        existing = await self.proposals.get_by_execution(run_id, node_execution_id)
        if existing is not None:
            self._ensure_replay_matches(existing, input)
            return ActionProposalResult(existing, True)
        ActionRequestService.validate_capability_parameters(input.capability, input.parameters)
        if input.rollback_capability is not None:
            ActionRequestService.validate_capability_parameters(
                input.rollback_capability, input.parameters
            )
        ActionRequestService.validate_rollback_capability(
            input.capability, input.rollback_capability
        )
        if any(not item.strip() or len(item) > 500 for item in input.verification_criteria):
            raise ApplicationError(
                "ACTION_PROPOSAL_VERIFICATION_INVALID",
                "Verification criteria must contain 1 to 500 characters",
                422,
            )

        run = await self.runs.get_run(run_id, for_update=True)
        if run is None:
            raise ApplicationError(
                "INVESTIGATION_RUN_NOT_FOUND", "Investigation run does not exist", 404
            )
        existing = await self.proposals.get_by_execution(run_id, node_execution_id)
        if existing is not None:
            self._ensure_replay_matches(existing, input)
            return ActionProposalResult(existing, True)
        incident = await self.incidents.get(run.incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        resource = await self.resources.get(input.resource_id)
        if resource is None or incident.resource_id != input.resource_id:
            raise ApplicationError(
                "ACTION_PROPOSAL_RESOURCE_OUT_OF_SCOPE",
                "Agent Action Proposal must target the Incident Resource",
                422,
            )
        step = await self._running_remediation_step(incident.id)
        if step is None:
            raise ApplicationError(
                "ACTION_PROPOSAL_STEP_INVALID",
                "Agent Action Proposal requires a running remediation PlanStep",
                409,
            )
        if step.resource_scope and str(input.resource_id) not in step.resource_scope:
            raise ApplicationError(
                "ACTION_PROPOSAL_RESOURCE_OUT_OF_SCOPE",
                "Action Proposal Resource is outside the active PlanStep scope",
                422,
            )
        if input.capability not in step.allowed_capabilities:
            raise ApplicationError(
                "ACTION_PROPOSAL_CAPABILITY_OUT_OF_SCOPE",
                "Action Proposal Capability is outside the active PlanStep allowlist",
                422,
            )
        if step.risk != input.risk:
            raise ApplicationError(
                "ACTION_PROPOSAL_RISK_MISMATCH",
                "Action Proposal risk must match the active PlanStep risk",
                422,
            )

        now = datetime.now(UTC)
        try:
            async with self.session.begin_nested():
                proposal = await self.proposals.create(
                    run_id=run.id,
                    node_execution_id=node_execution_id,
                    plan_step_id=step.id,
                    environment_id=resource.environment_id,
                    incident_id=incident.id,
                    resource_id=resource.id,
                    capability=input.capability,
                    parameters=dict(input.parameters),
                    verification_criteria=list(input.verification_criteria),
                    rollback_capability=input.rollback_capability,
                    risk=input.risk.value,
                    status=ActionProposalStatus.PROPOSED,
                    version=1,
                )
        except IntegrityError:
            existing = await self.proposals.get_by_execution(run_id, node_execution_id)
            if existing is None:
                raise
            self._ensure_replay_matches(existing, input)
            return ActionProposalResult(existing, True)
        decision, snapshot_id, _ = await PolicyService(self.session).evaluate(
            environment_id=resource.environment_id,
            incident_id=incident.id,
            resource_id=resource.id,
            capability=input.capability,
            autonomy_level=AutonomyLevel(incident.autonomy_level),
            risk=input.risk,
            commit=False,
        )
        proposal.policy_decision_id = snapshot_id
        proposal.decision_reason = decision.reason
        if not decision.allowed:
            proposal.status = ActionProposalStatus.DENIED
        elif decision.approval_required:
            from app.services.approvals import ApprovalService

            approval = await ApprovalService(self.session).create(
                policy_decision_id=snapshot_id,
                parameters=input.parameters,
                editable_parameter_keys=[],
                expires_in_seconds=1800,
                commit=False,
            )
            proposal.approval_id = approval.id
            proposal.status = ActionProposalStatus.AWAITING_APPROVAL
        else:
            action, _ = await ActionRequestService(self.session).create(
                policy_decision_id=snapshot_id,
                approval_id=None,
                parameters=input.parameters,
                verification_criteria=input.verification_criteria,
                rollback_capability=input.rollback_capability,
                idempotency_key=f"agent:{run.id}:{node_execution_id}",
                commit=False,
            )
            proposal.action_request_id = action.id
            proposal.status = ActionProposalStatus.ACTION_READY
        proposal.updated_at = now
        await self._event(proposal, "action.proposal_created", now)
        await commit_session(self.session)
        return ActionProposalResult(proposal, False)

    async def resolve_approval(
        self, approval: ApprovalRecord, now: datetime
    ) -> ActionProposalRecord | None:
        proposal = await self.proposals.get_by_approval(approval.id, for_update=True)
        if proposal is None or proposal.status != ActionProposalStatus.AWAITING_APPROVAL:
            return proposal
        if approval.status == ApprovalStatus.APPROVED:
            if proposal.policy_decision_id is None:
                raise ApplicationError(
                    "ACTION_PROPOSAL_POLICY_MISSING",
                    "Action Proposal is missing its Policy Decision",
                    409,
                )
            action, _ = await ActionRequestService(self.session).create(
                policy_decision_id=proposal.policy_decision_id,
                approval_id=approval.id,
                parameters=approval.parameters,
                verification_criteria=proposal.verification_criteria,
                rollback_capability=proposal.rollback_capability,
                idempotency_key=f"agent:{proposal.run_id}:{proposal.node_execution_id}",
                commit=False,
            )
            proposal.action_request_id = action.id
            proposal.status = ActionProposalStatus.ACTION_READY
        else:
            proposal.status = ActionProposalStatus.REJECTED
        proposal.version += 1
        proposal.updated_at = now
        await self._event(proposal, "action.proposal_resolved", now)
        return proposal

    async def list(
        self,
        incident_id: UUID | None,
        status: ActionProposalStatus | None,
        limit: int,
        offset: int,
    ) -> list[ActionProposalRecord]:
        return await self.proposals.list(incident_id, status, limit, offset)

    async def count(
        self,
        incident_id: UUID | None,
        status: ActionProposalStatus | None,
    ) -> int:
        return await self.proposals.count(incident_id, status)

    async def _running_remediation_step(self, incident_id: UUID):  # type: ignore[no-untyped-def]
        plan = await self.plans.get_latest(incident_id)
        if plan is None:
            return None
        return next(
            (
                step
                for step in await self.plans.list_steps(plan.id)
                if step.status == PlanStepStatus.RUNNING
                and step.step_type in {PlanStepType.REMEDIATE, PlanStepType.EXPERIMENT}
            ),
            None,
        )

    async def _event(self, proposal: ActionProposalRecord, event_type: str, now: datetime) -> None:
        incident = await self.incidents.get(proposal.incident_id)
        if incident is not None:
            await self.events.record(
                incident,
                event_type,
                now,
                "agent",
                {
                    "proposalId": str(proposal.id),
                    "runId": str(proposal.run_id),
                    "capability": proposal.capability,
                    "status": proposal.status.value,
                    "policyDecisionId": (
                        str(proposal.policy_decision_id) if proposal.policy_decision_id else None
                    ),
                    "approvalId": str(proposal.approval_id) if proposal.approval_id else None,
                    "actionId": (
                        str(proposal.action_request_id) if proposal.action_request_id else None
                    ),
                },
                aggregate_type="action_proposal",
                aggregate_id=proposal.id,
                aggregate_version=proposal.version,
            )

    @staticmethod
    def _ensure_replay_matches(proposal: ActionProposalRecord, input: ActionProposalInput) -> None:
        if not (
            proposal.resource_id == input.resource_id
            and proposal.capability == input.capability
            and proposal.parameters == input.parameters
            and proposal.verification_criteria == input.verification_criteria
            and proposal.rollback_capability == input.rollback_capability
            and proposal.risk == input.risk.value
        ):
            raise ApplicationError(
                "ACTION_PROPOSAL_IDEMPOTENCY_CONFLICT",
                "Node execution already produced a different Action Proposal",
                409,
            )
