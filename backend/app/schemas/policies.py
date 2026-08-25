from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.plans import PlanStepRisk
from app.domain.policies import AutonomyLevel, PolicyEffect
from app.schemas.base import ApiModel


class PolicyRuleCreate(ApiModel):
    environment_id: UUID
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    priority: int = Field(default=0, ge=-10000, le=10000)
    enabled: bool = True
    effect: PolicyEffect
    autonomy_levels: list[AutonomyLevel] = Field(default_factory=list, max_length=5)
    risk_levels: list[PlanStepRisk] = Field(default_factory=list, max_length=4)
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    resource_ids: list[UUID] = Field(default_factory=list, max_length=100)
    approval_required: bool = False
    maintenance_days: list[int] = Field(default_factory=list, max_length=7)
    maintenance_start_minute: int | None = Field(default=None, ge=0, le=1439)
    maintenance_end_minute: int | None = Field(default=None, ge=1, le=1440)
    max_executions_per_incident: int | None = Field(default=None, ge=1, le=10000)

    @model_validator(mode="after")
    def validate_maintenance_window(self) -> "PolicyRuleCreate":
        if len(set(self.maintenance_days)) != len(self.maintenance_days) or any(
            day < 0 or day > 6 for day in self.maintenance_days
        ):
            raise ValueError("maintenanceDays must contain unique weekdays from 0 to 6")
        bounds = (self.maintenance_start_minute, self.maintenance_end_minute)
        if (bounds[0] is None) != (bounds[1] is None):
            raise ValueError("maintenance window start and end must be set together")
        if bounds[0] is not None and bounds[1] is not None and bounds[0] >= bounds[1]:
            raise ValueError("maintenance window must not be empty or cross UTC midnight")
        if self.maintenance_days and bounds[0] is None:
            raise ValueError("maintenanceDays require a maintenance window")
        return self


class PolicyRuleUpdate(PolicyRuleCreate):
    expected_version: int = Field(ge=1)


class PolicyRuleResponse(ApiModel):
    id: UUID
    environment_id: UUID
    name: str
    description: str | None
    priority: int
    enabled: bool
    effect: PolicyEffect
    autonomy_levels: list[AutonomyLevel]
    risk_levels: list[PlanStepRisk]
    capabilities: list[str]
    resource_ids: list[UUID]
    approval_required: bool
    maintenance_days: list[int]
    maintenance_start_minute: int | None
    maintenance_end_minute: int | None
    max_executions_per_incident: int | None
    version: int
    created_at: datetime
    updated_at: datetime


class PolicyDryRunRequest(ApiModel):
    environment_id: UUID
    resource_id: UUID
    capability: str = Field(min_length=1, max_length=150)
    autonomy_level: AutonomyLevel
    risk: PlanStepRisk


class PolicyEvaluateRequest(PolicyDryRunRequest):
    incident_id: UUID


class PolicyDecisionResponse(ApiModel):
    allowed: bool
    approval_required: bool
    matched_rule_id: UUID | None
    matched_rule_name: str | None
    effect: PolicyEffect | None
    reason: str
    matched_rule_version: int | None
    remaining_executions: int | None


class PolicyDecisionSnapshotResponse(PolicyDecisionResponse):
    snapshot_id: UUID
    evaluated_at: datetime
