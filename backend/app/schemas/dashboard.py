from pydantic import Field

from app.schemas.base import ApiModel
from app.schemas.incidents import IncidentResponse


class DashboardSafetyResponse(ApiModel):
    pending_approvals: int = 0
    active_resource_locks: int = 0
    unknown_actions: int = 0
    actions_requiring_attention: int = 0
    observability_lost_incidents: int = 0


class DashboardResponse(ApiModel):
    active_tasks: int
    waiting_human: int
    root_cause_rate: int
    mean_investigation_seconds: int
    runner_online: int
    runner_total: int
    safety: DashboardSafetyResponse = Field(default_factory=DashboardSafetyResponse)
    incidents: list[IncidentResponse]
