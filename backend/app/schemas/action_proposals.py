from datetime import datetime
from uuid import UUID

from app.domain.actions import ActionProposalStatus
from app.domain.plans import PlanStepRisk
from app.schemas.base import ApiModel


class ActionProposalResponse(ApiModel):
    id: UUID
    run_id: UUID
    node_execution_id: str
    plan_step_id: UUID | None
    environment_id: UUID
    incident_id: UUID
    resource_id: UUID
    capability: str
    parameters: dict[str, object]
    verification_criteria: list[str]
    rollback_capability: str | None
    risk: PlanStepRisk
    status: ActionProposalStatus
    policy_decision_id: UUID | None
    approval_id: UUID | None
    action_request_id: UUID | None
    decision_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime
