from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, case, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal_context import principal_context
from app.domain.actions import ActionProposalStatus, ActionRequestStatus, CompensationStatus
from app.domain.alerts import AlertStatus
from app.domain.approvals import ApprovalStatus
from app.domain.hypotheses import HypothesisStatus
from app.domain.incidents import IncidentStatus, Severity
from app.domain.investigations import (
    InvestigationHITLSubjectType,
    InvestigationHITLWaitStatus,
    InvestigationObservationWaitStatus,
    InvestigationRunStatus,
)
from app.domain.plans import PlanStatus, PlanStepRisk, PlanStepType
from app.domain.policies import PolicyEffect
from app.domain.runner_tasks import RunnerTaskStatus
from app.domain.runners import RunnerStatus
from app.domain.security import PrincipalKind, PrincipalRole
from app.storage.models import (
    ActionExecutionRecord,
    ActionProposalRecord,
    ActionRequestRecord,
    ActionVerificationRecord,
    AlertRecord,
    ApiPrincipalRecord,
    ApprovalRecord,
    AuditArchiveBatchRecord,
    BrowserSessionRecord,
    CompensationExecutionRecord,
    CompensationRequestRecord,
    ControlPlaneAuditRecord,
    ControlPlaneSetupRecord,
    EnvironmentRecord,
    EvidenceRecord,
    HypothesisRecord,
    IncidentEventRecord,
    IncidentRecord,
    InvestigationCheckpointRecord,
    InvestigationHITLWaitRecord,
    InvestigationObservationWaitRecord,
    InvestigationRunRecord,
    OutboxEventRecord,
    PlanRecord,
    PlanStepRecord,
    PolicyDecisionRecord,
    PolicyRuleRecord,
    ResourceLockRecord,
    ResourceRecord,
    RunnerLeaseRecord,
    RunnerRecord,
    RunnerTaskRecord,
)


def _environment_scope() -> frozenset[UUID] | None:
    principal = principal_context.get()
    if principal is None or principal.unrestricted_environments:
        return None
    return principal.environment_ids


class PolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        environment_id: UUID,
        name: str,
        description: str | None,
        priority: int,
        enabled: bool,
        effect: PolicyEffect,
        autonomy_levels: builtins.list[str],
        risk_levels: builtins.list[str],
        capabilities: builtins.list[str],
        resource_ids: builtins.list[str],
        approval_required: bool,
        maintenance_days: builtins.list[int],
        maintenance_start_minute: int | None,
        maintenance_end_minute: int | None,
        max_executions_per_incident: int | None,
    ) -> PolicyRuleRecord:
        record = PolicyRuleRecord(
            environment_id=environment_id,
            name=name,
            description=description,
            priority=priority,
            enabled=enabled,
            effect=effect,
            autonomy_levels=autonomy_levels,
            risk_levels=risk_levels,
            capabilities=capabilities,
            resource_ids=resource_ids,
            approval_required=approval_required,
            maintenance_days=maintenance_days,
            maintenance_start_minute=maintenance_start_minute,
            maintenance_end_minute=maintenance_end_minute,
            max_executions_per_incident=max_executions_per_incident,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_for_environment(
        self,
        environment_id: UUID,
        *,
        enabled_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> builtins.list[PolicyRuleRecord]:
        scope = _environment_scope()
        if scope is not None and environment_id not in scope:
            return []
        statement = select(PolicyRuleRecord).where(
            PolicyRuleRecord.environment_id == environment_id
        )
        if enabled_only:
            statement = statement.where(PolicyRuleRecord.enabled.is_(True))
        statement = statement.order_by(
            PolicyRuleRecord.priority.desc(),
            PolicyRuleRecord.created_at,
            PolicyRuleRecord.id,
        )
        if limit is not None:
            statement = statement.limit(limit).offset(offset)
        return list(await self.session.scalars(statement))

    async def count_for_environment(
        self,
        environment_id: UUID,
        *,
        enabled_only: bool = False,
    ) -> int:
        scope = _environment_scope()
        if scope is not None and environment_id not in scope:
            return 0
        statement = (
            select(func.count())
            .select_from(PolicyRuleRecord)
            .where(PolicyRuleRecord.environment_id == environment_id)
        )
        if enabled_only:
            statement = statement.where(PolicyRuleRecord.enabled.is_(True))
        return int(await self.session.scalar(statement) or 0)

    async def get(self, policy_id: UUID, *, for_update: bool = False) -> PolicyRuleRecord | None:
        statement = select(PolicyRuleRecord).where(PolicyRuleRecord.id == policy_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(PolicyRuleRecord.environment_id.in_(scope))
        if for_update:
            statement = statement.with_for_update()
        record: PolicyRuleRecord | None = await self.session.scalar(statement)
        return record

    async def count_actions_for_incident_rule(self, incident_id: UUID, rule_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(ActionRequestRecord)
            .join(
                PolicyDecisionRecord,
                PolicyDecisionRecord.id == ActionRequestRecord.policy_decision_id,
            )
            .where(
                ActionRequestRecord.incident_id == incident_id,
                PolicyDecisionRecord.matched_rule_id == rule_id,
            )
        )
        return int(await self.session.scalar(statement) or 0)

    async def create_decision(self, **values: Any) -> PolicyDecisionRecord:
        record = PolicyDecisionRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_decision(
        self, snapshot_id: UUID, *, for_update: bool = False
    ) -> PolicyDecisionRecord | None:
        statement = select(PolicyDecisionRecord).where(PolicyDecisionRecord.id == snapshot_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(PolicyDecisionRecord.environment_id.in_(scope))
        if for_update:
            statement = statement.with_for_update()
        record: PolicyDecisionRecord | None = await self.session.scalar(statement)
        return record


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ApprovalRecord:
        record = ApprovalRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(self, approval_id: UUID, *, for_update: bool = False) -> ApprovalRecord | None:
        statement = select(ApprovalRecord).where(ApprovalRecord.id == approval_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ApprovalRecord.environment_id.in_(scope))
        if for_update:
            statement = statement.with_for_update()
        record: ApprovalRecord | None = await self.session.scalar(statement)
        return record

    async def get_by_snapshot(self, snapshot_id: UUID) -> ApprovalRecord | None:
        statement = select(ApprovalRecord).where(ApprovalRecord.policy_decision_id == snapshot_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ApprovalRecord.environment_id.in_(scope))
        record: ApprovalRecord | None = await self.session.scalar(statement)
        return record

    async def list(
        self,
        *,
        incident_id: UUID | None,
        status: ApprovalStatus | None,
        limit: int,
        offset: int,
    ) -> builtins.list[ApprovalRecord]:
        statement = select(ApprovalRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ApprovalRecord.environment_id.in_(scope))
        if incident_id is not None:
            statement = statement.where(ApprovalRecord.incident_id == incident_id)
        if status == ApprovalStatus.PENDING:
            statement = statement.where(
                ApprovalRecord.status == ApprovalStatus.PENDING,
                ApprovalRecord.expires_at > datetime.now(UTC),
            )
        elif status == ApprovalStatus.EXPIRED:
            statement = statement.where(
                or_(
                    ApprovalRecord.status == ApprovalStatus.EXPIRED,
                    (
                        (ApprovalRecord.status == ApprovalStatus.PENDING)
                        & (ApprovalRecord.expires_at <= datetime.now(UTC))
                    ),
                )
            )
        elif status is not None:
            statement = statement.where(ApprovalRecord.status == status)
        statement = (
            statement.order_by(ApprovalRecord.created_at.desc(), ApprovalRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(statement))

    async def count(
        self, *, incident_id: UUID | None, status: ApprovalStatus | None
    ) -> int:
        statement = select(func.count()).select_from(ApprovalRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ApprovalRecord.environment_id.in_(scope))
        if incident_id is not None:
            statement = statement.where(ApprovalRecord.incident_id == incident_id)
        now = datetime.now(UTC)
        if status == ApprovalStatus.PENDING:
            statement = statement.where(
                ApprovalRecord.status == ApprovalStatus.PENDING,
                ApprovalRecord.expires_at > now,
            )
        elif status == ApprovalStatus.EXPIRED:
            statement = statement.where(
                or_(
                    ApprovalRecord.status == ApprovalStatus.EXPIRED,
                    (
                        (ApprovalRecord.status == ApprovalStatus.PENDING)
                        & (ApprovalRecord.expires_at <= now)
                    ),
                )
            )
        elif status is not None:
            statement = statement.where(ApprovalRecord.status == status)
        return int(await self.session.scalar(statement) or 0)


class ActionProposalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ActionProposalRecord:
        record = ActionProposalRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_execution(
        self, run_id: UUID, node_execution_id: str
    ) -> ActionProposalRecord | None:
        statement = select(ActionProposalRecord).where(
            ActionProposalRecord.run_id == run_id,
            ActionProposalRecord.node_execution_id == node_execution_id,
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionProposalRecord.environment_id.in_(scope))
        record: ActionProposalRecord | None = await self.session.scalar(statement)
        return record

    async def get_by_approval(
        self, approval_id: UUID, *, for_update: bool = False
    ) -> ActionProposalRecord | None:
        statement = select(ActionProposalRecord).where(
            ActionProposalRecord.approval_id == approval_id
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionProposalRecord.environment_id.in_(scope))
        if for_update:
            statement = statement.with_for_update()
        record: ActionProposalRecord | None = await self.session.scalar(statement)
        return record

    async def list(
        self, incident_id: UUID | None, status: ActionProposalStatus | None, limit: int, offset: int
    ) -> builtins.list[ActionProposalRecord]:
        statement = select(ActionProposalRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionProposalRecord.environment_id.in_(scope))
        if incident_id is not None:
            statement = statement.where(ActionProposalRecord.incident_id == incident_id)
        if status is not None:
            statement = statement.where(ActionProposalRecord.status == status)
        statement = statement.order_by(
            ActionProposalRecord.created_at.desc(), ActionProposalRecord.id.desc()
        )
        return list(await self.session.scalars(statement.limit(limit).offset(offset)))

    async def count(
        self, incident_id: UUID | None, status: ActionProposalStatus | None
    ) -> int:
        statement = select(func.count()).select_from(ActionProposalRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionProposalRecord.environment_id.in_(scope))
        if incident_id is not None:
            statement = statement.where(ActionProposalRecord.incident_id == incident_id)
        if status is not None:
            statement = statement.where(ActionProposalRecord.status == status)
        return int(await self.session.scalar(statement) or 0)


class ActionRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ActionRequestRecord:
        record = ActionRequestRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(self, action_id: UUID, *, for_update: bool = False) -> ActionRequestRecord | None:
        statement = select(ActionRequestRecord).where(ActionRequestRecord.id == action_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionRequestRecord.environment_id.in_(scope))
        if for_update:
            statement = statement.with_for_update()
        record: ActionRequestRecord | None = await self.session.scalar(statement)
        return record

    async def get_by_idempotency_key(
        self, environment_id: UUID, idempotency_key: str
    ) -> ActionRequestRecord | None:
        statement = select(ActionRequestRecord).where(
            ActionRequestRecord.environment_id == environment_id,
            ActionRequestRecord.idempotency_key == idempotency_key,
        )
        scope = _environment_scope()
        if scope is not None and environment_id not in scope:
            return None
        record: ActionRequestRecord | None = await self.session.scalar(statement)
        return record

    async def get_by_policy_decision(
        self, policy_decision_id: UUID
    ) -> ActionRequestRecord | None:
        statement = select(ActionRequestRecord).where(
            ActionRequestRecord.policy_decision_id == policy_decision_id
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionRequestRecord.environment_id.in_(scope))
        record: ActionRequestRecord | None = await self.session.scalar(statement)
        return record

    async def get_by_approval(self, approval_id: UUID) -> ActionRequestRecord | None:
        statement = select(ActionRequestRecord).where(
            ActionRequestRecord.approval_id == approval_id
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionRequestRecord.environment_id.in_(scope))
        record: ActionRequestRecord | None = await self.session.scalar(statement)
        return record

    async def list(
        self,
        *,
        incident_id: UUID | None,
        status: ActionRequestStatus | None,
        limit: int,
        offset: int,
    ) -> builtins.list[ActionRequestRecord]:
        statement = select(ActionRequestRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionRequestRecord.environment_id.in_(scope))
        if incident_id is not None:
            statement = statement.where(ActionRequestRecord.incident_id == incident_id)
        if status is not None:
            statement = statement.where(ActionRequestRecord.status == status)
        statement = (
            statement.order_by(
                ActionRequestRecord.created_at.desc(), ActionRequestRecord.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(statement))

    async def count(
        self, *, incident_id: UUID | None, status: ActionRequestStatus | None
    ) -> int:
        statement = select(func.count()).select_from(ActionRequestRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionRequestRecord.environment_id.in_(scope))
        if incident_id is not None:
            statement = statement.where(ActionRequestRecord.incident_id == incident_id)
        if status is not None:
            statement = statement.where(ActionRequestRecord.status == status)
        return int(await self.session.scalar(statement) or 0)

    async def count_by_statuses(self, statuses: set[ActionRequestStatus]) -> int:
        statement = select(func.count()).select_from(ActionRequestRecord)
        if statuses:
            statement = statement.where(ActionRequestRecord.status.in_(statuses))
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionRequestRecord.environment_id.in_(scope))
        return int(await self.session.scalar(statement) or 0)


class ResourceLockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ResourceLockRecord:
        record = ResourceLockRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_for_resource(
        self, resource_id: UUID, *, for_update: bool = False
    ) -> ResourceLockRecord | None:
        statement = select(ResourceLockRecord).where(ResourceLockRecord.resource_id == resource_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ResourceLockRecord.environment_id.in_(scope))
        if for_update:
            statement = statement.with_for_update()
        record: ResourceLockRecord | None = await self.session.scalar(statement)
        return record

    async def get_for_action(
        self, action_id: UUID, *, for_update: bool = False
    ) -> ResourceLockRecord | None:
        statement = select(ResourceLockRecord).where(
            ResourceLockRecord.action_request_id == action_id,
            ResourceLockRecord.released_at.is_(None),
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ResourceLockRecord.environment_id.in_(scope))
        if for_update:
            statement = statement.with_for_update()
        record: ResourceLockRecord | None = await self.session.scalar(statement)
        return record

    async def release_for_action(
        self, action_id: UUID, *, released_at: datetime, released_by: str
    ) -> ResourceLockRecord | None:
        record = await self.get_for_action(action_id, for_update=True)
        if record is None:
            return None
        record.released_at = released_at
        record.released_by = released_by
        record.expires_at = released_at
        record.updated_at = released_at
        return record

    async def list_active(
        self, *, limit: int, offset: int, now: datetime
    ) -> builtins.list[ResourceLockRecord]:
        statement = select(ResourceLockRecord).where(
            ResourceLockRecord.released_at.is_(None),
            or_(
                ResourceLockRecord.expires_at > now,
                ResourceLockRecord.reconciliation_required.is_(True),
            ),
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ResourceLockRecord.environment_id.in_(scope))
        statement = (
            statement.order_by(ResourceLockRecord.expires_at, ResourceLockRecord.id)
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(statement))

    async def count_active(self, now: datetime) -> int:
        statement = (
            select(func.count())
            .select_from(ResourceLockRecord)
            .where(
                ResourceLockRecord.released_at.is_(None),
                or_(
                    ResourceLockRecord.expires_at > now,
                    ResourceLockRecord.reconciliation_required.is_(True),
                ),
            )
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ResourceLockRecord.environment_id.in_(scope))
        return int(await self.session.scalar(statement) or 0)


class ActionExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ActionExecutionRecord:
        record = ActionExecutionRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_for_action(
        self, action_id: UUID, *, for_update: bool = False
    ) -> ActionExecutionRecord | None:
        statement = select(ActionExecutionRecord).where(
            ActionExecutionRecord.action_request_id == action_id
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ActionRequestRecord).where(
                ActionRequestRecord.environment_id.in_(scope)
            )
        if for_update:
            statement = statement.with_for_update()
        record: ActionExecutionRecord | None = await self.session.scalar(statement)
        return record

    async def claim_for_runner(self, runner_id: UUID) -> ActionExecutionRecord | None:
        statement = (
            select(ActionExecutionRecord)
            .where(
                ActionExecutionRecord.runner_id == runner_id,
                ActionExecutionRecord.status == ActionRequestStatus.DISPATCHING,
            )
            .order_by(ActionExecutionRecord.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        record: ActionExecutionRecord | None = await self.session.scalar(statement)
        return record

    async def get(
        self, execution_id: UUID, *, for_update: bool = False
    ) -> ActionExecutionRecord | None:
        statement = select(ActionExecutionRecord).where(ActionExecutionRecord.id == execution_id)
        if for_update:
            statement = statement.with_for_update()
        record: ActionExecutionRecord | None = await self.session.scalar(statement)
        return record

    async def expired_running(self, now: datetime) -> builtins.list[ActionExecutionRecord]:
        statement = (
            select(ActionExecutionRecord)
            .where(
                ActionExecutionRecord.status == ActionRequestStatus.RUNNING,
                ActionExecutionRecord.lease_expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
        return list(await self.session.scalars(statement))


class ActionVerificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ActionVerificationRecord:
        record = ActionVerificationRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(
        self, verification_id: UUID, *, for_update: bool = False
    ) -> ActionVerificationRecord | None:
        statement = select(ActionVerificationRecord).where(
            ActionVerificationRecord.id == verification_id
        )
        if for_update:
            statement = statement.with_for_update()
        record: ActionVerificationRecord | None = await self.session.scalar(statement)
        return record

    async def get_for_action(
        self, action_id: UUID, *, for_update: bool = False
    ) -> ActionVerificationRecord | None:
        statement = select(ActionVerificationRecord).where(
            ActionVerificationRecord.action_request_id == action_id
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ActionVerificationRecord.environment_id.in_(scope))
        if for_update:
            statement = statement.with_for_update()
        record: ActionVerificationRecord | None = await self.session.scalar(statement)
        return record


class CompensationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> CompensationRequestRecord:
        record = CompensationRequestRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(
        self, compensation_id: UUID, *, for_update: bool = False
    ) -> CompensationRequestRecord | None:
        statement = select(CompensationRequestRecord).where(
            CompensationRequestRecord.id == compensation_id
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(CompensationRequestRecord.environment_id.in_(scope))
        if for_update:
            statement = statement.with_for_update()
        record: CompensationRequestRecord | None = await self.session.scalar(statement)
        return record

    async def get_for_action(self, action_id: UUID) -> CompensationRequestRecord | None:
        statement = select(CompensationRequestRecord).where(
            CompensationRequestRecord.action_request_id == action_id
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(CompensationRequestRecord.environment_id.in_(scope))
        record: CompensationRequestRecord | None = await self.session.scalar(statement)
        return record

    async def get_by_key(self, environment_id: UUID, key: str) -> CompensationRequestRecord | None:
        statement = select(CompensationRequestRecord).where(
            CompensationRequestRecord.environment_id == environment_id,
            CompensationRequestRecord.idempotency_key == key,
        )
        scope = _environment_scope()
        if scope is not None and environment_id not in scope:
            return None
        record: CompensationRequestRecord | None = await self.session.scalar(statement)
        return record

    async def list(
        self,
        *,
        incident_id: UUID | None,
        limit: int,
        offset: int,
    ) -> builtins.list[CompensationRequestRecord]:
        statement = select(CompensationRequestRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(CompensationRequestRecord.environment_id.in_(scope))
        if incident_id is not None:
            statement = statement.where(CompensationRequestRecord.incident_id == incident_id)
        statement = statement.order_by(
            CompensationRequestRecord.created_at.desc(), CompensationRequestRecord.id.desc()
        )
        return list(await self.session.scalars(statement.limit(limit).offset(offset)))

    async def count(self, *, incident_id: UUID | None) -> int:
        statement = select(func.count()).select_from(CompensationRequestRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(CompensationRequestRecord.environment_id.in_(scope))
        if incident_id is not None:
            statement = statement.where(CompensationRequestRecord.incident_id == incident_id)
        return int(await self.session.scalar(statement) or 0)


class CompensationExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> CompensationExecutionRecord:
        record = CompensationExecutionRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(
        self, execution_id: UUID, *, for_update: bool = False
    ) -> CompensationExecutionRecord | None:
        statement = select(CompensationExecutionRecord).where(
            CompensationExecutionRecord.id == execution_id
        )
        if for_update:
            statement = statement.with_for_update()
        record: CompensationExecutionRecord | None = await self.session.scalar(statement)
        return record

    async def get_for_request(
        self, compensation_id: UUID, *, for_update: bool = False
    ) -> CompensationExecutionRecord | None:
        statement = select(CompensationExecutionRecord).where(
            CompensationExecutionRecord.compensation_request_id == compensation_id
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(CompensationRequestRecord).where(
                CompensationRequestRecord.environment_id.in_(scope)
            )
        if for_update:
            statement = statement.with_for_update()
        record: CompensationExecutionRecord | None = await self.session.scalar(statement)
        return record

    async def claim_for_runner(self, runner_id: UUID) -> CompensationExecutionRecord | None:
        statement = (
            select(CompensationExecutionRecord)
            .where(
                CompensationExecutionRecord.runner_id == runner_id,
                CompensationExecutionRecord.status == CompensationStatus.DISPATCHING,
            )
            .order_by(CompensationExecutionRecord.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        record: CompensationExecutionRecord | None = await self.session.scalar(statement)
        return record

    async def expired_running(self, now: datetime) -> builtins.list[CompensationExecutionRecord]:
        statement = select(CompensationExecutionRecord).where(
            CompensationExecutionRecord.status == CompensationStatus.RUNNING,
            CompensationExecutionRecord.lease_expires_at <= now,
        )
        return list(await self.session.scalars(statement.with_for_update(skip_locked=True)))


class PrincipalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_token_hash(self, token_hash: str) -> ApiPrincipalRecord | None:
        statement = select(ApiPrincipalRecord).where(
            ApiPrincipalRecord.token_hash == token_hash,
            ApiPrincipalRecord.active.is_(True),
        )
        record: ApiPrincipalRecord | None = await self.session.scalar(statement)
        return record

    async def create(
        self,
        *,
        name: str,
        kind: PrincipalKind,
        role: PrincipalRole,
        token_hash: str,
        token_issued_at: datetime,
        token_expires_at: datetime,
        environment_ids: list[str],
        unrestricted_environments: bool,
    ) -> ApiPrincipalRecord:
        record = ApiPrincipalRecord(
            name=name,
            kind=kind,
            role=role,
            token_hash=token_hash,
            token_issued_at=token_issued_at,
            token_expires_at=token_expires_at,
            environment_ids=environment_ids,
            unrestricted_environments=unrestricted_environments,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def has_active_admin(self) -> bool:
        statement = (
            select(func.count())
            .select_from(ApiPrincipalRecord)
            .where(
                ApiPrincipalRecord.active.is_(True),
                ApiPrincipalRecord.kind == PrincipalKind.USER,
                ApiPrincipalRecord.role == PrincipalRole.ADMIN,
            )
        )
        return bool(await self.session.scalar(statement))

    async def lock_admin_deactivation(self) -> bool:
        await self.session.execute(
            update(ControlPlaneSetupRecord)
            .where(ControlPlaneSetupRecord.key == "initial_admin")
            .values(key="initial_admin")
        )
        return await self.get_initial_admin_setup(for_update=True) is not None

    async def count_active_unrestricted_admins(
        self,
        *,
        exclude_id: UUID | None = None,
        now: datetime,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(ApiPrincipalRecord)
            .where(
                ApiPrincipalRecord.active.is_(True),
                ApiPrincipalRecord.kind == PrincipalKind.USER,
                ApiPrincipalRecord.role == PrincipalRole.ADMIN,
                ApiPrincipalRecord.unrestricted_environments.is_(True),
                ApiPrincipalRecord.token_expires_at > now,
            )
        )
        if exclude_id is not None:
            statement = statement.where(ApiPrincipalRecord.id != exclude_id)
        return int(await self.session.scalar(statement) or 0)

    async def get_initial_admin_setup(
        self,
        *,
        for_update: bool = False,
    ) -> ControlPlaneSetupRecord | None:
        statement = select(ControlPlaneSetupRecord).where(
            ControlPlaneSetupRecord.key == "initial_admin"
        )
        if for_update:
            statement = statement.with_for_update()
        record: ControlPlaneSetupRecord | None = await self.session.scalar(statement)
        return record

    async def create_initial_admin_setup(self) -> ControlPlaneSetupRecord:
        record = ControlPlaneSetupRecord(key="initial_admin")
        self.session.add(record)
        await self.session.flush()
        return record

    async def list(self, *, limit: int, offset: int) -> builtins.list[ApiPrincipalRecord]:
        statement = (
            select(ApiPrincipalRecord)
            .order_by(ApiPrincipalRecord.name, ApiPrincipalRecord.id)
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(statement))

    async def count(self) -> int:
        statement = select(func.count()).select_from(ApiPrincipalRecord)
        return int(await self.session.scalar(statement) or 0)

    async def get(
        self,
        principal_id: UUID,
        *,
        for_update: bool = False,
    ) -> ApiPrincipalRecord | None:
        statement = select(ApiPrincipalRecord).where(ApiPrincipalRecord.id == principal_id)
        if for_update:
            statement = statement.with_for_update()
        record: ApiPrincipalRecord | None = await self.session.scalar(statement)
        return record


class BrowserSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> BrowserSessionRecord:
        record = BrowserSessionRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_token_hash(
        self,
        token_hash: str,
        *,
        for_update: bool = False,
    ) -> BrowserSessionRecord | None:
        statement = select(BrowserSessionRecord).where(
            BrowserSessionRecord.token_hash == token_hash
        )
        if for_update:
            statement = statement.with_for_update()
        record: BrowserSessionRecord | None = await self.session.scalar(statement)
        return record

    async def revoke_for_principal(self, principal_id: UUID, revoked_at: datetime) -> None:
        records = list(
            await self.session.scalars(
                select(BrowserSessionRecord).where(
                    BrowserSessionRecord.principal_id == principal_id,
                    BrowserSessionRecord.revoked_at.is_(None),
                )
            )
        )
        for record in records:
            record.revoked_at = revoked_at
            record.updated_at = revoked_at


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ControlPlaneAuditRecord:
        record = ControlPlaneAuditRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def list(
        self,
        limit: int,
        offset: int,
        *,
        actor_id: str | None = None,
        action: str | None = None,
        outcome: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
    ) -> builtins.list[ControlPlaneAuditRecord]:
        statement = select(ControlPlaneAuditRecord)
        statement = self._apply_filters(
            statement,
            actor_id=actor_id,
            action=action,
            outcome=outcome,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        )
        statement = statement.order_by(
            ControlPlaneAuditRecord.occurred_at.desc(),
            ControlPlaneAuditRecord.id.desc(),
        ).limit(limit).offset(offset)
        return list(await self.session.scalars(statement))

    async def count(
        self,
        *,
        actor_id: str | None = None,
        action: str | None = None,
        outcome: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
    ) -> int:
        statement = select(func.count()).select_from(ControlPlaneAuditRecord)
        statement = self._apply_filters(
            statement,
            actor_id=actor_id,
            action=action,
            outcome=outcome,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        )
        return int(await self.session.scalar(statement) or 0)

    @staticmethod
    def _apply_filters(
        statement: Any,
        *,
        actor_id: str | None,
        action: str | None,
        outcome: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
    ) -> Any:
        if actor_id is not None:
            statement = statement.where(ControlPlaneAuditRecord.actor_id == actor_id)
        if action is not None:
            statement = statement.where(ControlPlaneAuditRecord.action == action)
        if outcome is not None:
            statement = statement.where(ControlPlaneAuditRecord.outcome == outcome)
        if occurred_from is not None:
            statement = statement.where(ControlPlaneAuditRecord.occurred_at >= occurred_from)
        if occurred_to is not None:
            statement = statement.where(ControlPlaneAuditRecord.occurred_at <= occurred_to)
        return statement

    async def list_before(
        self,
        cutoff: datetime,
        limit: int,
        *,
        for_update: bool = False,
    ) -> builtins.list[ControlPlaneAuditRecord]:
        statement = (
            select(ControlPlaneAuditRecord)
            .where(ControlPlaneAuditRecord.occurred_at < cutoff)
            .order_by(ControlPlaneAuditRecord.occurred_at, ControlPlaneAuditRecord.id)
            .limit(limit)
        )
        if for_update:
            statement = statement.with_for_update(skip_locked=True)
        return list(await self.session.scalars(statement))

    async def delete_ids(self, record_ids: builtins.list[UUID]) -> int:
        if not record_ids:
            return 0
        result = await self.session.execute(
            delete(ControlPlaneAuditRecord).where(ControlPlaneAuditRecord.id.in_(record_ids))
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def recent_auth_failure_count(
        self,
        *,
        source_ip: str | None,
        since: datetime,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(ControlPlaneAuditRecord)
            .where(
                ControlPlaneAuditRecord.action == "auth.session.create",
                ControlPlaneAuditRecord.outcome == "failure",
                ControlPlaneAuditRecord.occurred_at >= since,
            )
        )
        if source_ip is None:
            statement = statement.where(ControlPlaneAuditRecord.source_ip.is_(None))
        else:
            statement = statement.where(ControlPlaneAuditRecord.source_ip == source_ip)
        return int(await self.session.scalar(statement) or 0)


class AuditArchiveRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> AuditArchiveBatchRecord:
        record = AuditArchiveBatchRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

@dataclass(frozen=True, slots=True)
class IncidentListItem:
    incident: IncidentRecord
    resource_name: str
    environment_name: str
    hypothesis: HypothesisRecord | None


class EnvironmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, name: str, slug: str, description: str | None) -> EnvironmentRecord:
        record = EnvironmentRecord(name=name, slug=slug, description=description)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(self, environment_id: UUID) -> EnvironmentRecord | None:
        statement = select(EnvironmentRecord).where(EnvironmentRecord.id == environment_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(EnvironmentRecord.id.in_(scope))
        record: EnvironmentRecord | None = await self.session.scalar(statement)
        return record

    async def list(self, limit: int, offset: int) -> list[EnvironmentRecord]:
        statement = select(EnvironmentRecord).order_by(
            EnvironmentRecord.name, EnvironmentRecord.id
        ).limit(limit)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(EnvironmentRecord.id.in_(scope))
        result = await self.session.scalars(statement.offset(offset))
        return list(result)

    async def count(self) -> int:
        statement = select(func.count()).select_from(EnvironmentRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(EnvironmentRecord.id.in_(scope))
        return int(await self.session.scalar(statement) or 0)


class ResourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        environment_id: UUID,
        name: str,
        kind: str,
        criticality: str,
        attributes: dict[str, object],
    ) -> ResourceRecord:
        record = ResourceRecord(
            environment_id=environment_id,
            name=name,
            kind=kind,
            criticality=criticality,
            attributes=attributes,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(self, resource_id: UUID) -> ResourceRecord | None:
        statement = select(ResourceRecord).where(ResourceRecord.id == resource_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ResourceRecord.environment_id.in_(scope))
        record: ResourceRecord | None = await self.session.scalar(statement)
        return record

    async def list(self, limit: int, offset: int) -> list[ResourceRecord]:
        statement = select(ResourceRecord).order_by(
            ResourceRecord.name, ResourceRecord.id
        ).limit(limit)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ResourceRecord.environment_id.in_(scope))
        result = await self.session.scalars(statement.offset(offset))
        return list(result)

    async def count(self) -> int:
        statement = select(func.count()).select_from(ResourceRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(ResourceRecord.environment_id.in_(scope))
        return int(await self.session.scalar(statement) or 0)

    async def find_unique_by_names(
        self,
        names: builtins.list[str],
    ) -> ResourceRecord | None:
        if not names:
            return None
        statement = select(ResourceRecord).where(ResourceRecord.name.in_(names)).limit(2)
        records = list(await self.session.scalars(statement))
        return records[0] if len(records) == 1 else None


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        title: str,
        severity: Severity,
        resource_id: UUID,
        owner: str | None,
    ) -> IncidentRecord:
        record = IncidentRecord(
            title=title,
            status=IncidentStatus.DETECTED,
            severity=severity,
            resource_id=resource_id,
            owner=owner,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(self, incident_id: UUID, *, for_update: bool = False) -> IncidentRecord | None:
        statement = select(IncidentRecord).where(IncidentRecord.id == incident_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        if for_update:
            statement = statement.with_for_update()
        record: IncidentRecord | None = await self.session.scalar(statement)
        return record

    async def list(
        self,
        limit: int,
        offset: int,
        status: IncidentStatus | None,
        severity: Severity | None,
        environment_id: UUID | None = None,
        query: str | None = None,
    ) -> list[IncidentListItem]:
        statement = (
            self._view_statement()
            .order_by(IncidentRecord.updated_at.desc(), IncidentRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        statement = self._apply_list_filters(
            statement,
            status=status,
            severity=severity,
            environment_id=environment_id,
            query=query,
        )
        rows = await self.session.execute(statement)
        return [IncidentListItem(*row) for row in rows.tuples()]

    async def count(
        self,
        status: IncidentStatus | None,
        severity: Severity | None,
        environment_id: UUID | None = None,
        query: str | None = None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(IncidentRecord)
            .join(ResourceRecord, ResourceRecord.id == IncidentRecord.resource_id)
            .join(EnvironmentRecord, EnvironmentRecord.id == ResourceRecord.environment_id)
        )
        statement = self._apply_list_filters(
            statement,
            status=status,
            severity=severity,
            environment_id=environment_id,
            query=query,
        )
        return int(await self.session.scalar(statement) or 0)

    @staticmethod
    def _apply_list_filters(
        statement: Any,
        *,
        status: IncidentStatus | None,
        severity: Severity | None,
        environment_id: UUID | None,
        query: str | None,
    ) -> Any:
        if status is not None:
            statement = statement.where(IncidentRecord.status == status)
        if severity is not None:
            statement = statement.where(IncidentRecord.severity == severity)
        if environment_id is not None:
            statement = statement.where(EnvironmentRecord.id == environment_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(EnvironmentRecord.id.in_(scope))
        normalized_query = query.strip() if query is not None else ""
        if normalized_query:
            pattern = f"%{normalized_query}%"
            compact_id_pattern = f"%{normalized_query.replace('-', '')}%"
            statement = statement.where(
                or_(
                    cast(IncidentRecord.id, String).ilike(pattern),
                    cast(IncidentRecord.id, String).ilike(compact_id_pattern),
                    IncidentRecord.title.ilike(pattern),
                    cast(ResourceRecord.id, String).ilike(pattern),
                    cast(ResourceRecord.id, String).ilike(compact_id_pattern),
                    ResourceRecord.name.ilike(pattern),
                    IncidentRecord.owner.ilike(pattern),
                )
            )
        return statement

    async def get_view(self, incident_id: UUID) -> IncidentListItem | None:
        statement = self._view_statement().where(IncidentRecord.id == incident_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(EnvironmentRecord.id.in_(scope))
        row = (await self.session.execute(statement)).tuples().one_or_none()
        return IncidentListItem(*row) if row else None

    @staticmethod
    def _view_statement() -> Any:
        primary_hypothesis_id = (
            select(HypothesisRecord.id)
            .where(
                HypothesisRecord.incident_id == IncidentRecord.id,
                HypothesisRecord.status != HypothesisStatus.REJECTED,
            )
            .order_by(
                HypothesisRecord.confidence.desc(),
                HypothesisRecord.updated_at.desc(),
            )
            .limit(1)
            .correlate(IncidentRecord)
            .scalar_subquery()
        )
        return (
            select(
                IncidentRecord,
                ResourceRecord.name,
                EnvironmentRecord.name,
                HypothesisRecord,
            )
            .join(ResourceRecord, ResourceRecord.id == IncidentRecord.resource_id)
            .join(EnvironmentRecord, EnvironmentRecord.id == ResourceRecord.environment_id)
            .outerjoin(HypothesisRecord, HypothesisRecord.id == primary_hypothesis_id)
        )

    async def list_observability_lost_for_runner(
        self,
        runner_id: UUID,
    ) -> builtins.list[IncidentRecord]:
        statement = select(IncidentRecord).where(
            IncidentRecord.status == IncidentStatus.OBSERVABILITY_LOST,
            IncidentRecord.observability_runner_id == runner_id,
        )
        return list(await self.session.scalars(statement.with_for_update()))

    async def add_event(
        self,
        incident_id: UUID,
        event_type: str,
        occurred_at: datetime,
        actor_type: str,
        actor_id: str | None,
        payload: dict[str, object],
    ) -> IncidentEventRecord:
        event = IncidentEventRecord(
            incident_id=incident_id,
            event_type=event_type,
            occurred_at=occurred_at,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def advance_event_cursor(self, incident_id: UUID, sequence: int) -> int:
        statement = (
            update(IncidentRecord)
            .where(IncidentRecord.id == incident_id)
            .values(
                event_cursor=case(
                    (IncidentRecord.event_cursor < sequence, sequence),
                    else_=IncidentRecord.event_cursor,
                )
            )
            .returning(IncidentRecord.event_cursor)
            .execution_options(synchronize_session=False)
        )
        cursor = await self.session.scalar(statement)
        if cursor is None:
            raise RuntimeError(f"Incident {incident_id} disappeared while recording an event")
        return int(cursor)

    async def list_events(
        self,
        incident_id: UUID,
        *,
        limit: int,
        offset: int = 0,
    ) -> builtins.list[IncidentEventRecord]:
        statement = (
            select(IncidentEventRecord)
            .where(IncidentEventRecord.incident_id == incident_id)
            .order_by(
                IncidentEventRecord.occurred_at.desc(),
                IncidentEventRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(statement))

    async def count_events(self, incident_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(IncidentEventRecord)
            .where(IncidentEventRecord.incident_id == incident_id)
        )
        return int(await self.session.scalar(statement) or 0)

    async def count_by_statuses(self, statuses: set[IncidentStatus]) -> int:
        statement = select(func.count()).select_from(IncidentRecord)
        if statuses:
            statement = statement.where(IncidentRecord.status.in_(statuses))
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        return int(await self.session.scalar(statement) or 0)

    async def list_completed(self) -> builtins.list[IncidentRecord]:
        statement = select(IncidentRecord).where(
            IncidentRecord.status.in_({IncidentStatus.RESOLVED, IncidentStatus.CLOSED})
        )
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        return list(await self.session.scalars(statement))

    async def find_active_for_resource(
        self,
        resource_id: UUID,
        updated_after: datetime,
    ) -> IncidentRecord | None:
        terminal = {
            IncidentStatus.RESOLVED,
            IncidentStatus.CLOSED,
            IncidentStatus.FAILED,
            IncidentStatus.CANCELLED,
        }
        statement = (
            select(IncidentRecord)
            .where(
                IncidentRecord.resource_id == resource_id,
                IncidentRecord.status.not_in(terminal),
                IncidentRecord.updated_at >= updated_after,
            )
            .order_by(IncidentRecord.updated_at.desc())
            .limit(1)
            .with_for_update()
        )
        record: IncidentRecord | None = await self.session.scalar(statement)
        return record


class PlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_latest(self, incident_id: UUID) -> PlanRecord | None:
        statement = (
            select(PlanRecord)
            .where(PlanRecord.incident_id == incident_id)
            .order_by(PlanRecord.version.desc())
            .limit(1)
        )
        scope = _environment_scope()
        if scope is not None:
            statement = (
                statement.join(IncidentRecord)
                .join(ResourceRecord)
                .where(ResourceRecord.environment_id.in_(scope))
            )
        record: PlanRecord | None = await self.session.scalar(statement)
        return record

    async def get(self, plan_id: UUID) -> PlanRecord | None:
        statement = select(PlanRecord).where(PlanRecord.id == plan_id)
        scope = _environment_scope()
        if scope is not None:
            statement = (
                statement.join(IncidentRecord)
                .join(ResourceRecord)
                .where(ResourceRecord.environment_id.in_(scope))
            )
        record: PlanRecord | None = await self.session.scalar(statement)
        return record

    async def create(
        self,
        incident_id: UUID,
        version: int,
        objective: str,
        max_tool_calls: int,
        max_duration_seconds: int,
        replan_count: int,
    ) -> PlanRecord:
        record = PlanRecord(
            incident_id=incident_id,
            version=version,
            objective=objective,
            status=PlanStatus.ACTIVE,
            max_tool_calls=max_tool_calls,
            max_duration_seconds=max_duration_seconds,
            replan_count=replan_count,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def add_step(
        self,
        plan_id: UUID,
        ordinal: int,
        title: str,
        objective: str,
        step_type: PlanStepType,
        dependencies: list[str],
        resource_scope: list[str],
        allowed_capabilities: list[str],
        expected_evidence: list[str],
        success_criteria: list[str],
        risk: PlanStepRisk,
    ) -> PlanStepRecord:
        record = PlanStepRecord(
            plan_id=plan_id,
            ordinal=ordinal,
            title=title,
            objective=objective,
            step_type=step_type,
            dependencies=dependencies,
            resource_scope=resource_scope,
            allowed_capabilities=allowed_capabilities,
            expected_evidence=expected_evidence,
            success_criteria=success_criteria,
            risk=risk,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_steps(self, plan_id: UUID) -> list[PlanStepRecord]:
        statement = (
            select(PlanStepRecord)
            .where(PlanStepRecord.plan_id == plan_id)
            .order_by(PlanStepRecord.ordinal)
        )
        return list(await self.session.scalars(statement))

    async def get_step_for_incident(
        self,
        incident_id: UUID,
        step_id: UUID,
        *,
        for_update: bool = False,
    ) -> PlanStepRecord | None:
        statement = (
            select(PlanStepRecord)
            .join(PlanRecord, PlanRecord.id == PlanStepRecord.plan_id)
            .where(PlanRecord.incident_id == incident_id, PlanStepRecord.id == step_id)
        )
        if for_update:
            statement = statement.with_for_update()
        record: PlanStepRecord | None = await self.session.scalar(statement)
        return record


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        incident_id: UUID,
        trace_id: UUID,
        aggregate_version: int,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> OutboxEventRecord:
        record = OutboxEventRecord(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            incident_id=incident_id,
            trace_id=trace_id,
            aggregate_version=aggregate_version,
            payload=payload,
            occurred_at=occurred_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_after(
        self,
        incident_id: UUID,
        sequence: int,
        limit: int = 100,
    ) -> list[OutboxEventRecord]:
        statement = (
            select(OutboxEventRecord)
            .where(
                OutboxEventRecord.incident_id == incident_id,
                OutboxEventRecord.sequence > sequence,
            )
            .order_by(OutboxEventRecord.sequence)
            .limit(limit)
        )
        return list(await self.session.scalars(statement))

    async def pending_for_publish(
        self,
        limit: int,
        now: datetime | None = None,
    ) -> list[OutboxEventRecord]:
        statement = (
            select(OutboxEventRecord)
            .where(
                OutboxEventRecord.published_at.is_(None),
                OutboxEventRecord.dead_lettered_at.is_(None),
                or_(
                    OutboxEventRecord.next_attempt_at.is_(None),
                    OutboxEventRecord.next_attempt_at <= (now or datetime.now(UTC)),
                ),
            )
            .order_by(OutboxEventRecord.sequence)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(await self.session.scalars(statement))

    async def get_by_event_id(
        self,
        event_id: UUID,
        *,
        for_update: bool = False,
    ) -> OutboxEventRecord | None:
        statement = select(OutboxEventRecord).where(OutboxEventRecord.event_id == event_id)
        if for_update:
            statement = statement.with_for_update()
        record: OutboxEventRecord | None = await self.session.scalar(statement)
        return record

    async def list_dead_letters(
        self,
        limit: int,
        offset: int,
    ) -> list[OutboxEventRecord]:
        statement = (
            select(OutboxEventRecord)
            .where(OutboxEventRecord.dead_lettered_at.is_not(None))
            .order_by(OutboxEventRecord.dead_lettered_at.desc(), OutboxEventRecord.sequence)
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(statement))

    async def count_dead_letters(self) -> int:
        statement = (
            select(func.count())
            .select_from(OutboxEventRecord)
            .where(OutboxEventRecord.dead_lettered_at.is_not(None))
        )
        return int(await self.session.scalar(statement) or 0)

    async def delivery_stats(self) -> tuple[int, int, datetime | None]:
        pending_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(
                    OutboxEventRecord.published_at.is_(None),
                    OutboxEventRecord.dead_lettered_at.is_(None),
                )
            )
            or 0
        )
        dead_letter_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(OutboxEventRecord)
                .where(OutboxEventRecord.dead_lettered_at.is_not(None))
            )
            or 0
        )
        oldest = await self.session.scalar(
            select(func.min(OutboxEventRecord.occurred_at)).where(
                OutboxEventRecord.published_at.is_(None),
                OutboxEventRecord.dead_lettered_at.is_(None),
            )
        )
        return pending_count, dead_letter_count, oldest

    async def delete_published_before(self, cutoff: datetime, limit: int) -> int:
        sequences = (
            select(OutboxEventRecord.sequence)
            .where(
                OutboxEventRecord.published_at.is_not(None),
                OutboxEventRecord.published_at < cutoff,
            )
            .order_by(OutboxEventRecord.sequence)
            .limit(limit)
        )
        selected = list(await self.session.scalars(sequences))
        if not selected:
            return 0
        await self.session.execute(
            delete(OutboxEventRecord).where(OutboxEventRecord.sequence.in_(selected))
        )
        return len(selected)


class AlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_dedup_key(self, source: str, dedup_key: str) -> AlertRecord | None:
        statement = (
            select(AlertRecord)
            .where(AlertRecord.source == source, AlertRecord.dedup_key == dedup_key)
            .with_for_update()
        )
        record: AlertRecord | None = await self.session.scalar(statement)
        return record

    async def create(
        self,
        *,
        source: str,
        dedup_key: str,
        fingerprint: str,
        status: AlertStatus,
        severity: Severity,
        title: str,
        labels: dict[str, str],
        annotations: dict[str, str],
        starts_at: datetime,
        ends_at: datetime | None,
        received_at: datetime,
        generator_url: str | None,
        raw_payload_hash: str,
        resource_id: UUID | None,
    ) -> AlertRecord:
        record = AlertRecord(
            source=source,
            dedup_key=dedup_key,
            fingerprint=fingerprint,
            status=status,
            severity=severity,
            title=title,
            labels=labels,
            annotations=annotations,
            starts_at=starts_at,
            ends_at=ends_at,
            received_at=received_at,
            last_seen_at=received_at,
            generator_url=generator_url,
            raw_payload_hash=raw_payload_hash,
            resource_id=resource_id,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list(
        self,
        limit: int,
        offset: int,
        status: AlertStatus | None,
        resource_id: UUID | None,
        incident_id: UUID | None,
    ) -> builtins.list[AlertRecord]:
        statement = (
            select(AlertRecord)
            .order_by(AlertRecord.last_seen_at.desc(), AlertRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            statement = statement.where(AlertRecord.status == status)
        if resource_id is not None:
            statement = statement.where(AlertRecord.resource_id == resource_id)
        if incident_id is not None:
            statement = statement.where(AlertRecord.incident_id == incident_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        return list(await self.session.scalars(statement))

    async def count(
        self,
        status: AlertStatus | None,
        resource_id: UUID | None,
        incident_id: UUID | None,
    ) -> int:
        statement = select(func.count()).select_from(AlertRecord)
        if status is not None:
            statement = statement.where(AlertRecord.status == status)
        if resource_id is not None:
            statement = statement.where(AlertRecord.resource_id == resource_id)
        if incident_id is not None:
            statement = statement.where(AlertRecord.incident_id == incident_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        return int(await self.session.scalar(statement) or 0)


class RunnerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, runner_id: UUID, *, for_update: bool = False) -> RunnerRecord | None:
        statement = select(RunnerRecord).where(RunnerRecord.id == runner_id)
        if for_update:
            statement = statement.with_for_update()
        record: RunnerRecord | None = await self.session.scalar(statement)
        return record

    async def get_by_name(self, name: str) -> RunnerRecord | None:
        statement = select(RunnerRecord).where(RunnerRecord.name == name)
        record: RunnerRecord | None = await self.session.scalar(statement)
        return record

    async def create(
        self,
        *,
        name: str,
        software_version: str,
        environment_id: UUID | None,
        capabilities: list[dict[str, Any]],
        labels: dict[str, str],
        token_hash: str,
        token_issued_at: datetime,
        token_expires_at: datetime,
        now: datetime,
        lease_expires_at: datetime,
    ) -> RunnerRecord:
        record = RunnerRecord(
            name=name,
            status=RunnerStatus.ONLINE,
            software_version=software_version,
            environment_id=environment_id,
            capabilities={"connectors": capabilities},
            labels=labels,
            token_hash=token_hash,
            token_issued_at=token_issued_at,
            token_expires_at=token_expires_at,
            last_seen_at=now,
            lease_expires_at=lease_expires_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list(
        self,
        limit: int,
        offset: int,
        status: RunnerStatus | None,
    ) -> builtins.list[RunnerRecord]:
        statement = (
            select(RunnerRecord)
            .order_by(RunnerRecord.name, RunnerRecord.id)
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            statement = statement.where(RunnerRecord.status == status)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(RunnerRecord.environment_id.in_(scope))
        return list(await self.session.scalars(statement))

    async def count(self, status: RunnerStatus | None) -> int:
        statement = select(func.count()).select_from(RunnerRecord)
        if status is not None:
            statement = statement.where(RunnerRecord.status == status)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(RunnerRecord.environment_id.in_(scope))
        return int(await self.session.scalar(statement) or 0)

    async def list_for_connector_catalog(
        self, environment_id: UUID | None
    ) -> builtins.list[RunnerRecord]:
        statement = select(RunnerRecord).order_by(RunnerRecord.name)
        scope = _environment_scope()
        if environment_id is not None:
            statement = statement.where(
                or_(
                    RunnerRecord.environment_id == environment_id,
                    RunnerRecord.environment_id.is_(None),
                )
            )
        elif scope is not None:
            statement = statement.where(
                or_(
                    RunnerRecord.environment_id.in_(scope),
                    RunnerRecord.environment_id.is_(None),
                )
            )
        return list(await self.session.scalars(statement))

    async def dashboard_counts(self, now: datetime) -> tuple[int, int]:
        statement = select(
            func.count(),
            func.count().filter(
                RunnerRecord.status == RunnerStatus.ONLINE,
                RunnerRecord.lease_expires_at > now,
            ),
        ).select_from(RunnerRecord)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.where(
                or_(
                    RunnerRecord.environment_id.in_(scope),
                    RunnerRecord.environment_id.is_(None),
                )
            )
        total, online = (await self.session.execute(statement)).one()
        return int(total or 0), int(online or 0)

    async def expired_online(self, now: datetime) -> builtins.list[RunnerRecord]:
        statement = (
            select(RunnerRecord)
            .where(
                RunnerRecord.status == RunnerStatus.ONLINE,
                RunnerRecord.lease_expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
        return list(await self.session.scalars(statement))

    async def online_for_environment(
        self, environment_id: UUID, now: datetime
    ) -> builtins.list[RunnerRecord]:
        statement = (
            select(RunnerRecord)
            .where(
                RunnerRecord.status == RunnerStatus.ONLINE,
                RunnerRecord.lease_expires_at > now,
                or_(
                    RunnerRecord.environment_id == environment_id,
                    RunnerRecord.environment_id.is_(None),
                ),
            )
            .order_by(RunnerRecord.last_seen_at.desc())
        )
        return list(await self.session.scalars(statement))


class RunnerLeaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        runner_id: UUID,
        renewed_at: datetime,
        expires_at: datetime,
    ) -> RunnerLeaseRecord:
        record = RunnerLeaseRecord(
            runner_id=runner_id,
            fencing_token=1,
            renewed_at=renewed_at,
            expires_at=expires_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_for_runner(
        self,
        runner_id: UUID,
        *,
        for_update: bool = False,
    ) -> RunnerLeaseRecord | None:
        statement = select(RunnerLeaseRecord).where(RunnerLeaseRecord.runner_id == runner_id)
        if for_update:
            statement = statement.with_for_update()
        record: RunnerLeaseRecord | None = await self.session.scalar(statement)
        return record


class EvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        incident_id: UUID,
        resource_id: UUID,
        evidence_type: str,
        source: str,
        summary: str,
        content_hash: str,
        redacted: bool,
        observed_from: datetime | None,
        observed_to: datetime | None,
        collected_at: datetime,
        collection_status: str,
        time_confidence: str,
        data: dict[str, Any],
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            incident_id=incident_id,
            resource_id=resource_id,
            evidence_type=evidence_type,
            source=source,
            summary=summary,
            content_hash=content_hash,
            redacted=redacted,
            observed_from=observed_from,
            observed_to=observed_to,
            collected_at=collected_at,
            collection_status=collection_status,
            time_confidence=time_confidence,
            data=data,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(self, evidence_id: UUID) -> EvidenceRecord | None:
        statement = select(EvidenceRecord).where(EvidenceRecord.id == evidence_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        record: EvidenceRecord | None = await self.session.scalar(statement)
        return record

    async def existing_ids_for_incident(
        self,
        incident_id: UUID,
        evidence_ids: set[UUID],
    ) -> set[UUID]:
        if not evidence_ids:
            return set()
        statement = select(EvidenceRecord.id).where(
            EvidenceRecord.incident_id == incident_id,
            EvidenceRecord.id.in_(evidence_ids),
        )
        return set(await self.session.scalars(statement))

    async def list_for_incident(
        self,
        incident_id: UUID,
        limit: int,
        offset: int,
        evidence_type: str | None,
        resource_id: UUID | None,
    ) -> list[EvidenceRecord]:
        statement = (
            select(EvidenceRecord)
            .where(EvidenceRecord.incident_id == incident_id)
            .order_by(
                EvidenceRecord.collected_at.desc(),
                EvidenceRecord.created_at.desc(),
                EvidenceRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        if evidence_type is not None:
            statement = statement.where(EvidenceRecord.evidence_type == evidence_type)
        if resource_id is not None:
            statement = statement.where(EvidenceRecord.resource_id == resource_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        return list(await self.session.scalars(statement))

    async def count_for_incident(
        self,
        incident_id: UUID,
        evidence_type: str | None,
        resource_id: UUID | None,
    ) -> int:
        statement = (
            select(func.count()).select_from(EvidenceRecord).where(
                EvidenceRecord.incident_id == incident_id
            )
        )
        if evidence_type is not None:
            statement = statement.where(EvidenceRecord.evidence_type == evidence_type)
        if resource_id is not None:
            statement = statement.where(EvidenceRecord.resource_id == resource_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        return int(await self.session.scalar(statement) or 0)


class HypothesisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        incident_id: UUID,
        summary: str,
        confidence: int,
        supporting_evidence_ids: builtins.list[str],
        contradicting_evidence_ids: builtins.list[str],
    ) -> HypothesisRecord:
        ordinal_statement = select(func.max(HypothesisRecord.ordinal)).where(
            HypothesisRecord.incident_id == incident_id
        )
        ordinal = int(await self.session.scalar(ordinal_statement) or 0) + 1
        record = HypothesisRecord(
            incident_id=incident_id,
            ordinal=ordinal,
            summary=summary,
            confidence=confidence,
            status=HypothesisStatus.PROPOSED,
            supporting_evidence_ids=supporting_evidence_ids,
            contradicting_evidence_ids=contradicting_evidence_ids,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(
        self,
        hypothesis_id: UUID,
        *,
        for_update: bool = False,
    ) -> HypothesisRecord | None:
        statement = select(HypothesisRecord).where(HypothesisRecord.id == hypothesis_id)
        if for_update:
            statement = statement.with_for_update()
        record: HypothesisRecord | None = await self.session.scalar(statement)
        return record

    async def list_for_incident(
        self, incident_id: UUID, limit: int, offset: int
    ) -> builtins.list[HypothesisRecord]:
        statement = (
            select(HypothesisRecord)
            .where(HypothesisRecord.incident_id == incident_id)
            .order_by(
                HypothesisRecord.confidence.desc(),
                HypothesisRecord.ordinal,
                HypothesisRecord.id,
            )
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(statement))

    async def count_for_incident(self, incident_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(HypothesisRecord)
            .where(HypothesisRecord.incident_id == incident_id)
        )
        return int(await self.session.scalar(statement) or 0)

    async def existing_ids_for_incident(
        self,
        incident_id: UUID,
        hypothesis_ids: set[UUID],
    ) -> set[UUID]:
        if not hypothesis_ids:
            return set()
        statement = select(HypothesisRecord.id).where(
            HypothesisRecord.incident_id == incident_id,
            HypothesisRecord.id.in_(hypothesis_ids),
        )
        return set(await self.session.scalars(statement))


class InvestigationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_run(
        self,
        run_id: UUID,
        *,
        for_update: bool = False,
    ) -> InvestigationRunRecord | None:
        statement = select(InvestigationRunRecord).where(InvestigationRunRecord.id == run_id)
        scope = _environment_scope()
        if scope is not None:
            statement = (
                statement.join(IncidentRecord)
                .join(ResourceRecord)
                .where(ResourceRecord.environment_id.in_(scope))
            )
        if for_update:
            statement = statement.with_for_update()
        record: InvestigationRunRecord | None = await self.session.scalar(statement)
        return record

    async def get_run_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> InvestigationRunRecord | None:
        statement = select(InvestigationRunRecord).where(
            InvestigationRunRecord.idempotency_key == idempotency_key
        )
        record: InvestigationRunRecord | None = await self.session.scalar(statement)
        return record

    async def get_active_for_incident(
        self,
        incident_id: UUID,
    ) -> InvestigationRunRecord | None:
        statement = (
            select(InvestigationRunRecord)
            .where(
                InvestigationRunRecord.incident_id == incident_id,
                InvestigationRunRecord.status.in_(
                    {
                        InvestigationRunStatus.QUEUED,
                        InvestigationRunStatus.RUNNING,
                        InvestigationRunStatus.PAUSED,
                    }
                ),
            )
            .order_by(InvestigationRunRecord.created_at.desc())
            .with_for_update()
            .limit(1)
        )
        record: InvestigationRunRecord | None = await self.session.scalar(statement)
        return record

    async def create_run(self, **values: Any) -> InvestigationRunRecord:
        record = InvestigationRunRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def claim_runtime_candidate(
        self,
        *,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> tuple[InvestigationRunRecord, InvestigationRunStatus] | None:
        statement = (
            select(InvestigationRunRecord)
            .where(
                or_(
                    InvestigationRunRecord.status == InvestigationRunStatus.QUEUED,
                    (
                        (InvestigationRunRecord.status == InvestigationRunStatus.RUNNING)
                        & or_(
                            InvestigationRunRecord.runtime_lease_expires_at.is_(None),
                            InvestigationRunRecord.runtime_lease_expires_at <= now,
                        )
                    ),
                )
            )
            .order_by(InvestigationRunRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        record: InvestigationRunRecord | None = await self.session.scalar(statement)
        if record is None:
            return None
        previous = record.status
        record.status = InvestigationRunStatus.RUNNING
        record.runtime_owner = owner
        record.runtime_lease_expires_at = lease_expires_at
        record.runtime_attempt += 1
        record.version += 1
        record.updated_at = now
        if record.started_at is None:
            record.started_at = now
        await self.session.flush()
        return record, previous

    async def renew_runtime_lease(
        self,
        run_id: UUID,
        owner: str,
        lease_expires_at: datetime,
    ) -> bool:
        record = await self.get_run(run_id, for_update=True)
        if (
            record is None
            or record.status != InvestigationRunStatus.RUNNING
            or record.runtime_owner != owner
        ):
            return False
        record.runtime_lease_expires_at = lease_expires_at
        await self.session.flush()
        return True

    async def list_runs_for_incident(
        self,
        incident_id: UUID,
        limit: int,
        offset: int,
    ) -> builtins.list[InvestigationRunRecord]:
        statement = (
            select(InvestigationRunRecord)
            .where(InvestigationRunRecord.incident_id == incident_id)
            .order_by(
                InvestigationRunRecord.created_at.desc(),
                InvestigationRunRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(statement))

    async def count_runs_for_incident(self, incident_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(InvestigationRunRecord)
            .where(InvestigationRunRecord.incident_id == incident_id)
        )
        return int(await self.session.scalar(statement) or 0)

    async def get_checkpoint_by_node_execution(
        self,
        run_id: UUID,
        node_execution_id: str,
    ) -> InvestigationCheckpointRecord | None:
        statement = select(InvestigationCheckpointRecord).where(
            InvestigationCheckpointRecord.run_id == run_id,
            InvestigationCheckpointRecord.node_execution_id == node_execution_id,
        )
        record: InvestigationCheckpointRecord | None = await self.session.scalar(statement)
        return record

    async def get_checkpoint(self, checkpoint_id: UUID) -> InvestigationCheckpointRecord | None:
        record: InvestigationCheckpointRecord | None = await self.session.scalar(
            select(InvestigationCheckpointRecord).where(
                InvestigationCheckpointRecord.id == checkpoint_id
            )
        )
        return record

    async def create_checkpoint(self, **values: Any) -> InvestigationCheckpointRecord:
        record = InvestigationCheckpointRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_checkpoints(
        self,
        run_id: UUID,
        after_sequence: int,
        limit: int,
    ) -> builtins.list[InvestigationCheckpointRecord]:
        statement = (
            select(InvestigationCheckpointRecord)
            .where(
                InvestigationCheckpointRecord.run_id == run_id,
                InvestigationCheckpointRecord.sequence > after_sequence,
            )
            .order_by(InvestigationCheckpointRecord.sequence)
            .limit(limit)
        )
        return list(await self.session.scalars(statement))

    async def get_latest_checkpoint(
        self,
        run_id: UUID,
    ) -> InvestigationCheckpointRecord | None:
        statement = (
            select(InvestigationCheckpointRecord)
            .where(InvestigationCheckpointRecord.run_id == run_id)
            .order_by(InvestigationCheckpointRecord.sequence.desc())
            .limit(1)
        )
        record: InvestigationCheckpointRecord | None = await self.session.scalar(statement)
        return record

    async def get_hitl_wait(
        self, run_id: UUID, subject_type: InvestigationHITLSubjectType, subject_id: UUID
    ) -> InvestigationHITLWaitRecord | None:
        record: InvestigationHITLWaitRecord | None = await self.session.scalar(
            select(InvestigationHITLWaitRecord).where(
                InvestigationHITLWaitRecord.run_id == run_id,
                InvestigationHITLWaitRecord.subject_type == subject_type,
                InvestigationHITLWaitRecord.subject_id == subject_id,
            )
        )
        return record

    async def get_waiting_hitl_for_subject(
        self, subject_type: InvestigationHITLSubjectType, subject_id: UUID
    ) -> InvestigationHITLWaitRecord | None:
        record: InvestigationHITLWaitRecord | None = await self.session.scalar(
            select(InvestigationHITLWaitRecord)
            .where(
                InvestigationHITLWaitRecord.subject_type == subject_type,
                InvestigationHITLWaitRecord.subject_id == subject_id,
                InvestigationHITLWaitRecord.status == InvestigationHITLWaitStatus.WAITING,
            )
            .with_for_update()
        )
        return record

    async def latest_resolved_hitl_wait(self, run_id: UUID) -> InvestigationHITLWaitRecord | None:
        record: InvestigationHITLWaitRecord | None = await self.session.scalar(
            select(InvestigationHITLWaitRecord)
            .where(
                InvestigationHITLWaitRecord.run_id == run_id,
                InvestigationHITLWaitRecord.status == InvestigationHITLWaitStatus.RESOLVED,
            )
            .order_by(InvestigationHITLWaitRecord.resolved_at.desc())
            .limit(1)
        )
        return record

    async def list_hitl_waits(
        self, run_id: UUID, limit: int, offset: int
    ) -> list[InvestigationHITLWaitRecord]:
        return list(
            await self.session.scalars(
                select(InvestigationHITLWaitRecord)
                .where(InvestigationHITLWaitRecord.run_id == run_id)
                .order_by(
                    InvestigationHITLWaitRecord.created_at,
                    InvestigationHITLWaitRecord.id,
                )
                .limit(limit)
                .offset(offset)
            )
        )

    async def count_hitl_waits(self, run_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(InvestigationHITLWaitRecord)
            .where(InvestigationHITLWaitRecord.run_id == run_id)
        )
        return int(await self.session.scalar(statement) or 0)

    async def waiting_hitl_waits_for_run(self, run_id: UUID) -> list[InvestigationHITLWaitRecord]:
        return list(
            await self.session.scalars(
                select(InvestigationHITLWaitRecord)
                .where(
                    InvestigationHITLWaitRecord.run_id == run_id,
                    InvestigationHITLWaitRecord.status == InvestigationHITLWaitStatus.WAITING,
                )
                .with_for_update()
            )
        )

    async def create_hitl_wait(self, **values: Any) -> InvestigationHITLWaitRecord:
        record = InvestigationHITLWaitRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_observation_wait_by_execution(
        self, run_id: UUID, node_execution_id: str
    ) -> InvestigationObservationWaitRecord | None:
        record: InvestigationObservationWaitRecord | None = await self.session.scalar(
            select(InvestigationObservationWaitRecord).where(
                InvestigationObservationWaitRecord.run_id == run_id,
                InvestigationObservationWaitRecord.node_execution_id == node_execution_id,
            )
        )
        return record

    async def get_waiting_observation_for_task(
        self, runner_task_id: UUID
    ) -> InvestigationObservationWaitRecord | None:
        record: InvestigationObservationWaitRecord | None = await self.session.scalar(
            select(InvestigationObservationWaitRecord)
            .where(
                InvestigationObservationWaitRecord.runner_task_id == runner_task_id,
                InvestigationObservationWaitRecord.status
                == InvestigationObservationWaitStatus.WAITING,
            )
            .with_for_update()
        )
        return record

    async def waiting_observation_waits_for_run(
        self, run_id: UUID
    ) -> list[InvestigationObservationWaitRecord]:
        return list(
            await self.session.scalars(
                select(InvestigationObservationWaitRecord)
                .where(
                    InvestigationObservationWaitRecord.run_id == run_id,
                    InvestigationObservationWaitRecord.status
                    == InvestigationObservationWaitStatus.WAITING,
                )
                .with_for_update()
            )
        )

    async def latest_resolved_observation_wait(
        self, run_id: UUID
    ) -> InvestigationObservationWaitRecord | None:
        record: InvestigationObservationWaitRecord | None = await self.session.scalar(
            select(InvestigationObservationWaitRecord)
            .where(
                InvestigationObservationWaitRecord.run_id == run_id,
                InvestigationObservationWaitRecord.status
                == InvestigationObservationWaitStatus.RESOLVED,
            )
            .order_by(InvestigationObservationWaitRecord.resolved_at.desc())
            .limit(1)
        )
        return record

    async def create_observation_wait(
        self, **values: Any
    ) -> InvestigationObservationWaitRecord:
        record = InvestigationObservationWaitRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record


class RunnerTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, task_id: UUID, *, for_update: bool = False) -> RunnerTaskRecord | None:
        statement = select(RunnerTaskRecord).where(RunnerTaskRecord.id == task_id)
        if for_update:
            statement = statement.with_for_update()
        record: RunnerTaskRecord | None = await self.session.scalar(statement)
        return record

    async def get_by_idempotency_key(self, key: str) -> RunnerTaskRecord | None:
        statement = select(RunnerTaskRecord).where(RunnerTaskRecord.idempotency_key == key)
        record: RunnerTaskRecord | None = await self.session.scalar(statement)
        return record

    async def get_for_verification(self, verification_id: UUID) -> RunnerTaskRecord | None:
        statement = select(RunnerTaskRecord).where(
            RunnerTaskRecord.action_verification_id == verification_id
        )
        record: RunnerTaskRecord | None = await self.session.scalar(statement)
        return record

    async def create(self, **values: Any) -> RunnerTaskRecord:
        record = RunnerTaskRecord(**values)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_active_for_runner(self, runner_id: UUID) -> RunnerTaskRecord | None:
        statement = (
            select(RunnerTaskRecord)
            .where(
                RunnerTaskRecord.runner_id == runner_id,
                RunnerTaskRecord.status == RunnerTaskStatus.LEASED,
            )
            .order_by(RunnerTaskRecord.updated_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        record: RunnerTaskRecord | None = await self.session.scalar(statement)
        return record

    async def queued_candidates(self, runner_id: UUID, limit: int = 50) -> list[RunnerTaskRecord]:
        statement = (
            select(RunnerTaskRecord)
            .where(
                RunnerTaskRecord.status == RunnerTaskStatus.QUEUED,
                or_(
                    RunnerTaskRecord.runner_id.is_(None),
                    RunnerTaskRecord.runner_id == runner_id,
                ),
            )
            .order_by(RunnerTaskRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        return list(await self.session.scalars(statement))

    async def expired_leases(self, now: datetime) -> list[RunnerTaskRecord]:
        statement = (
            select(RunnerTaskRecord)
            .where(
                RunnerTaskRecord.status == RunnerTaskStatus.LEASED,
                RunnerTaskRecord.lease_expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
        return list(await self.session.scalars(statement))

    async def leased_for_runner(self, runner_id: UUID) -> list[RunnerTaskRecord]:
        statement = (
            select(RunnerTaskRecord)
            .where(
                RunnerTaskRecord.runner_id == runner_id,
                RunnerTaskRecord.status == RunnerTaskStatus.LEASED,
            )
            .with_for_update(skip_locked=True)
        )
        return list(await self.session.scalars(statement))

    async def active_for_plan(self, plan_id: UUID) -> list[RunnerTaskRecord]:
        statement = (
            select(RunnerTaskRecord)
            .join(PlanStepRecord, PlanStepRecord.id == RunnerTaskRecord.plan_step_id)
            .where(
                PlanStepRecord.plan_id == plan_id,
                RunnerTaskRecord.status.in_({RunnerTaskStatus.QUEUED, RunnerTaskStatus.LEASED}),
            )
            .with_for_update(skip_locked=True)
        )
        return list(await self.session.scalars(statement))

    async def active_for_plan_step(self, plan_step_id: UUID) -> list[RunnerTaskRecord]:
        statement = (
            select(RunnerTaskRecord)
            .where(
                RunnerTaskRecord.plan_step_id == plan_step_id,
                RunnerTaskRecord.status.in_({RunnerTaskStatus.QUEUED, RunnerTaskStatus.LEASED}),
            )
            .with_for_update(skip_locked=True)
        )
        return list(await self.session.scalars(statement))

    async def list(
        self,
        limit: int,
        offset: int,
        status: RunnerTaskStatus | None,
        incident_id: UUID | None,
        runner_id: UUID | None,
        plan_step_id: UUID | None,
    ) -> list[RunnerTaskRecord]:
        statement = (
            select(RunnerTaskRecord)
            .order_by(RunnerTaskRecord.created_at.desc(), RunnerTaskRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            statement = statement.where(RunnerTaskRecord.status == status)
        if incident_id is not None:
            statement = statement.where(RunnerTaskRecord.incident_id == incident_id)
        if runner_id is not None:
            statement = statement.where(RunnerTaskRecord.runner_id == runner_id)
        if plan_step_id is not None:
            statement = statement.where(RunnerTaskRecord.plan_step_id == plan_step_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        return list(await self.session.scalars(statement))

    async def count(
        self,
        status: RunnerTaskStatus | None,
        incident_id: UUID | None,
        runner_id: UUID | None,
        plan_step_id: UUID | None,
    ) -> int:
        statement = select(func.count()).select_from(RunnerTaskRecord)
        if status is not None:
            statement = statement.where(RunnerTaskRecord.status == status)
        if incident_id is not None:
            statement = statement.where(RunnerTaskRecord.incident_id == incident_id)
        if runner_id is not None:
            statement = statement.where(RunnerTaskRecord.runner_id == runner_id)
        if plan_step_id is not None:
            statement = statement.where(RunnerTaskRecord.plan_step_id == plan_step_id)
        scope = _environment_scope()
        if scope is not None:
            statement = statement.join(ResourceRecord).where(
                ResourceRecord.environment_id.in_(scope)
            )
        return int(await self.session.scalar(statement) or 0)
