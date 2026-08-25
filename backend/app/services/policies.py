from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.core.principal_context import principal_context
from app.domain.plans import PlanStepRisk
from app.domain.policies import AutonomyLevel, PolicyEffect
from app.storage.models import PolicyDecisionRecord, PolicyRuleRecord
from app.storage.repositories import (
    EnvironmentRepository,
    IncidentRepository,
    PolicyRepository,
    ResourceRepository,
)
from app.storage.transactions import commit_session


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    approval_required: bool
    matched_rule_id: UUID | None
    matched_rule_name: str | None
    effect: PolicyEffect | None
    reason: str
    matched_rule_version: int | None
    remaining_executions: int | None


class PolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.environments = EnvironmentRepository(session)
        self.resources = ResourceRepository(session)
        self.incidents = IncidentRepository(session)
        self.policies = PolicyRepository(session)

    async def create_rule(
        self,
        *,
        environment_id: UUID,
        name: str,
        description: str | None,
        priority: int,
        enabled: bool,
        effect: PolicyEffect,
        autonomy_levels: list[str],
        risk_levels: list[str],
        capabilities: list[str],
        resource_ids: list[UUID],
        approval_required: bool,
        maintenance_days: list[int],
        maintenance_start_minute: int | None,
        maintenance_end_minute: int | None,
        max_executions_per_incident: int | None,
    ) -> PolicyRuleRecord:
        if await self.environments.get(environment_id) is None:
            raise ApplicationError("ENVIRONMENT_NOT_FOUND", "Environment does not exist", 404)
        for resource_id in resource_ids:
            resource = await self.resources.get(resource_id)
            if resource is None or resource.environment_id != environment_id:
                raise ApplicationError(
                    "POLICY_RESOURCE_SCOPE_INVALID",
                    "Every Policy resource must belong to its Environment",
                    422,
                )
        try:
            record = await self.policies.create(
                environment_id=environment_id,
                name=name,
                description=description,
                priority=priority,
                enabled=enabled,
                effect=effect,
                autonomy_levels=autonomy_levels,
                risk_levels=risk_levels,
                capabilities=capabilities,
                resource_ids=[str(item) for item in resource_ids],
                approval_required=approval_required,
                maintenance_days=maintenance_days,
                maintenance_start_minute=maintenance_start_minute,
                maintenance_end_minute=maintenance_end_minute,
                max_executions_per_incident=max_executions_per_incident,
            )
            await commit_session(self.session)
        except IntegrityError as exc:
            raise ApplicationError(
                "POLICY_RULE_CONFLICT",
                "Policy rule name already exists in this Environment",
                409,
            ) from exc
        return record

    async def update_rule(
        self,
        policy_id: UUID,
        *,
        expected_version: int,
        environment_id: UUID,
        name: str,
        description: str | None,
        priority: int,
        enabled: bool,
        effect: PolicyEffect,
        autonomy_levels: list[str],
        risk_levels: list[str],
        capabilities: list[str],
        resource_ids: list[UUID],
        approval_required: bool,
        maintenance_days: list[int],
        maintenance_start_minute: int | None,
        maintenance_end_minute: int | None,
        max_executions_per_incident: int | None,
    ) -> PolicyRuleRecord:
        record = await self.policies.get(policy_id, for_update=True)
        if record is None:
            raise ApplicationError("POLICY_RULE_NOT_FOUND", "Policy rule does not exist", 404)
        if record.version != expected_version:
            raise ApplicationError(
                "POLICY_RULE_VERSION_CONFLICT",
                "Policy rule has changed; reload before retrying",
                409,
            )
        if record.environment_id != environment_id:
            raise ApplicationError(
                "POLICY_ENVIRONMENT_IMMUTABLE",
                "Policy rule cannot be moved to another Environment",
                422,
            )
        await self._validate_resource_scope(record.environment_id, resource_ids)
        record.name = name
        record.description = description
        record.priority = priority
        record.enabled = enabled
        record.effect = effect
        record.autonomy_levels = autonomy_levels
        record.risk_levels = risk_levels
        record.capabilities = capabilities
        record.resource_ids = [str(item) for item in resource_ids]
        record.approval_required = approval_required
        record.maintenance_days = maintenance_days
        record.maintenance_start_minute = maintenance_start_minute
        record.maintenance_end_minute = maintenance_end_minute
        record.max_executions_per_incident = max_executions_per_incident
        record.version += 1
        record.updated_at = datetime.now(UTC)
        try:
            await commit_session(self.session)
        except IntegrityError as exc:
            raise ApplicationError(
                "POLICY_RULE_CONFLICT",
                "Policy rule name already exists in this Environment",
                409,
            ) from exc
        return record

    async def dry_run(
        self,
        *,
        environment_id: UUID,
        resource_id: UUID,
        capability: str,
        autonomy_level: AutonomyLevel,
        risk: PlanStepRisk,
    ) -> PolicyDecision:
        await self._validate_target(environment_id, resource_id)
        rules = await self.policies.list_for_environment(environment_id, enabled_only=True)
        return self._decide(
            rules, resource_id, capability, autonomy_level, risk, datetime.now(UTC), None
        )

    async def evaluate(
        self,
        *,
        environment_id: UUID,
        incident_id: UUID,
        resource_id: UUID,
        capability: str,
        autonomy_level: AutonomyLevel,
        risk: PlanStepRisk,
        commit: bool = True,
    ) -> tuple[PolicyDecision, UUID, datetime]:
        await self._validate_target(environment_id, resource_id)
        incident = await self.incidents.get(incident_id)
        if incident is None or incident.resource_id != resource_id:
            raise ApplicationError(
                "POLICY_INCIDENT_SCOPE_INVALID",
                "Policy evaluation Incident must belong to the target Resource",
                422,
            )
        rules = await self.policies.list_for_environment(environment_id, enabled_only=True)
        now = datetime.now(UTC)
        decision = self._decide(rules, resource_id, capability, autonomy_level, risk, now, None)
        if decision.matched_rule_id is not None:
            locked = await self.policies.get(decision.matched_rule_id, for_update=True)
            if (
                locked is None
                or not locked.enabled
                or locked.version != decision.matched_rule_version
            ):
                raise ApplicationError(
                    "POLICY_RULE_CHANGED",
                    "Policy rule changed during evaluation; retry with current rules",
                    409,
                )
            consumed = await self.policies.count_actions_for_incident_rule(incident_id, locked.id)
            decision = self._decide(
                [locked], resource_id, capability, autonomy_level, risk, now, consumed
            )
        actor = principal_context.get()
        snapshot = await self.policies.create_decision(
            evaluated_at=now,
            evaluated_by=actor.actor_id if actor else "system",
            environment_id=environment_id,
            incident_id=incident_id,
            resource_id=resource_id,
            capability=capability,
            autonomy_level=autonomy_level.value,
            risk=risk.value,
            allowed=decision.allowed,
            approval_required=decision.approval_required,
            matched_rule_id=decision.matched_rule_id,
            matched_rule_version=decision.matched_rule_version,
            effect=decision.effect.value if decision.effect else None,
            reason=decision.reason,
        )
        if commit:
            await commit_session(self.session)
        return decision, snapshot.id, now

    async def revalidate_snapshot(self, snapshot: PolicyDecisionRecord) -> PolicyDecision:
        await self._validate_target(snapshot.environment_id, snapshot.resource_id)
        rules = await self.policies.list_for_environment(snapshot.environment_id, enabled_only=True)
        return self._decide(
            rules,
            snapshot.resource_id,
            snapshot.capability,
            AutonomyLevel(snapshot.autonomy_level),
            PlanStepRisk(snapshot.risk),
            datetime.now(UTC),
            None,
        )

    async def authorize_action_creation(self, snapshot: PolicyDecisionRecord) -> PolicyDecision:
        """Revalidate and atomically reserve capacity under the matched Policy rule lock."""
        await self._validate_target(snapshot.environment_id, snapshot.resource_id)
        if snapshot.matched_rule_id is None:
            return self._decide(
                [],
                snapshot.resource_id,
                snapshot.capability,
                AutonomyLevel(snapshot.autonomy_level),
                PlanStepRisk(snapshot.risk),
                datetime.now(UTC),
                None,
            )
        rule = await self.policies.get(snapshot.matched_rule_id, for_update=True)
        if rule is None or not rule.enabled or rule.version != snapshot.matched_rule_version:
            raise ApplicationError(
                "POLICY_RULE_CHANGED",
                "Policy rule changed after the authorization decision",
                409,
            )
        consumed = await self.policies.count_actions_for_incident_rule(
            snapshot.incident_id, rule.id
        )
        return self._decide(
            [rule],
            snapshot.resource_id,
            snapshot.capability,
            AutonomyLevel(snapshot.autonomy_level),
            PlanStepRisk(snapshot.risk),
            datetime.now(UTC),
            consumed,
        )

    def _decide(
        self,
        rules: list[PolicyRuleRecord],
        resource_id: UUID,
        capability: str,
        autonomy_level: AutonomyLevel,
        risk: PlanStepRisk,
        evaluated_at: datetime,
        consumed: int | None,
    ) -> PolicyDecision:
        for rule in rules:
            if not self._matches(rule, resource_id, capability, autonomy_level, risk):
                continue
            allowed = rule.effect == PolicyEffect.ALLOW
            reason = f"Matched {rule.effect.value} rule '{rule.name}' at priority {rule.priority}"
            if allowed and not self._inside_maintenance_window(rule, evaluated_at):
                allowed = False
                reason = f"Rule '{rule.name}' matched, but the UTC maintenance window is closed"
            remaining: int | None = None
            if rule.max_executions_per_incident is not None and consumed is not None:
                remaining = max(rule.max_executions_per_incident - consumed, 0)
                if allowed and remaining == 0:
                    allowed = False
                    reason = f"Rule '{rule.name}' reached its per-Incident execution limit"
                elif allowed:
                    remaining -= 1
            return PolicyDecision(
                allowed=allowed,
                approval_required=allowed and rule.approval_required,
                matched_rule_id=rule.id,
                matched_rule_name=rule.name,
                effect=rule.effect,
                reason=reason,
                matched_rule_version=rule.version,
                remaining_executions=remaining,
            )
        return PolicyDecision(
            allowed=False,
            approval_required=False,
            matched_rule_id=None,
            matched_rule_name=None,
            effect=None,
            reason="No enabled Policy rule matched; default deny applies",
            matched_rule_version=None,
            remaining_executions=None,
        )

    async def _validate_target(self, environment_id: UUID, resource_id: UUID) -> None:
        if await self.environments.get(environment_id) is None:
            raise ApplicationError("ENVIRONMENT_NOT_FOUND", "Environment does not exist", 404)
        resource = await self.resources.get(resource_id)
        if resource is None or resource.environment_id != environment_id:
            raise ApplicationError("RESOURCE_NOT_FOUND", "Resource does not exist", 404)

    async def _validate_resource_scope(
        self, environment_id: UUID, resource_ids: list[UUID]
    ) -> None:
        for resource_id in resource_ids:
            resource = await self.resources.get(resource_id)
            if resource is None or resource.environment_id != environment_id:
                raise ApplicationError(
                    "POLICY_RESOURCE_SCOPE_INVALID",
                    "Every Policy resource must belong to its Environment",
                    422,
                )

    @staticmethod
    def _inside_maintenance_window(rule: PolicyRuleRecord, now: datetime) -> bool:
        if rule.maintenance_start_minute is None or rule.maintenance_end_minute is None:
            return True
        if rule.maintenance_days and now.weekday() not in rule.maintenance_days:
            return False
        minute = now.hour * 60 + now.minute
        return rule.maintenance_start_minute <= minute < rule.maintenance_end_minute

    @staticmethod
    def _matches(
        rule: PolicyRuleRecord,
        resource_id: UUID,
        capability: str,
        autonomy_level: AutonomyLevel,
        risk: PlanStepRisk,
    ) -> bool:
        return (
            (not rule.resource_ids or str(resource_id) in rule.resource_ids)
            and (not rule.capabilities or capability in rule.capabilities)
            and (not rule.autonomy_levels or autonomy_level.value in rule.autonomy_levels)
            and (not rule.risk_levels or risk.value in rule.risk_levels)
        )
