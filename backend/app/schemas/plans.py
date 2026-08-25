from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.domain.plans import PlanStatus, PlanStepRisk, PlanStepStatus, PlanStepType
from app.schemas.base import ApiModel


class PlanStepCreate(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    objective: str = Field(min_length=1, max_length=2000)
    kind: PlanStepType
    dependencies: list[str] = Field(default_factory=list, max_length=50)
    resource_scope: list[str] = Field(default_factory=list, max_length=100)
    allowed_capabilities: list[str] = Field(default_factory=list, max_length=100)
    expected_evidence: list[str] = Field(default_factory=list, max_length=100)
    success_criteria: list[str] = Field(default_factory=list, max_length=100)
    risk: PlanStepRisk


class PlanCreate(ApiModel):
    objective: str = Field(min_length=1, max_length=2000)
    max_tool_calls: int = Field(default=30, ge=1, le=500)
    max_duration_seconds: int = Field(default=900, ge=30, le=86400)
    steps: list[PlanStepCreate] = Field(min_length=1, max_length=50)


class PlanStepTransitionRequest(ApiModel):
    target: PlanStepStatus
    expected_version: int = Field(ge=1)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    result_summary: str | None = Field(default=None, max_length=5000)


class PlanStepResponse(ApiModel):
    id: UUID
    ordinal: int
    title: str
    objective: str
    kind: PlanStepType
    status: PlanStepStatus
    risk: PlanStepRisk
    attempts: int
    evidence_ids: list[str]
    result_summary: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class PlanResponse(ApiModel):
    id: UUID
    incident_id: UUID
    version: int
    objective: str
    status: PlanStatus
    max_tool_calls: int
    max_duration_seconds: int
    replan_count: int
    steps: list[PlanStepResponse]
    created_at: datetime
    updated_at: datetime


class ToolBudgetResponse(ApiModel):
    used: int
    limit: int
