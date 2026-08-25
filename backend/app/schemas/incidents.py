from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.domain.incidents import IncidentStatus, Severity
from app.schemas.base import ApiModel
from app.schemas.hypotheses import HypothesisSummary
from app.schemas.plans import PlanStepResponse, ToolBudgetResponse


class IncidentCreate(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    severity: Severity
    resource_id: UUID
    owner: str | None = Field(default=None, max_length=100)


class IncidentTransitionRequest(ApiModel):
    target: IncidentStatus
    expected_version: int = Field(ge=1)
    actor_id: str | None = Field(default=None, max_length=100)


class IncidentResponse(ApiModel):
    id: UUID
    title: str
    status: IncidentStatus
    severity: Severity
    resource: str
    environment: str
    resource_id: UUID
    owner: str | None
    version: int
    observability_status: Literal["observable", "lost"]
    observability_runner_id: UUID | None
    observability_lost_at: datetime | None
    hypothesis: HypothesisSummary | None
    created_at: datetime
    updated_at: datetime


class IncidentEventResponse(ApiModel):
    id: UUID
    type: str
    occurred_at: datetime
    actor_type: str
    actor_id: str | None
    payload: dict[str, Any]


class IncidentDetailResponse(IncidentResponse):
    trace_id: UUID
    event_cursor: int = Field(ge=0)
    autonomy_level: Literal["L0", "L1", "L2", "L3"]
    plan_version: int
    replan_count: int
    tool_budget: ToolBudgetResponse
    steps: list[PlanStepResponse]
    timeline: list[IncidentEventResponse]
    timeline_total: int = Field(ge=0)
    timeline_truncated: bool
