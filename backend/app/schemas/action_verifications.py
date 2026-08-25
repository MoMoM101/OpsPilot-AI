from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.actions import ActionVerificationStatus
from app.schemas.base import ApiModel


class ActionVerificationResponse(ApiModel):
    id: UUID
    action_request_id: UUID
    environment_id: UUID
    incident_id: UUID
    resource_id: UUID
    runner_task_id: UUID | None = None
    status: ActionVerificationStatus
    criteria_snapshot: list[str]
    connector: str
    operation: str
    parameters: dict[str, Any]
    result_summary: str | None
    error_code: str | None
    evidence_id: UUID | None
    compensation_required: bool
    started_at: datetime | None
    completed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
