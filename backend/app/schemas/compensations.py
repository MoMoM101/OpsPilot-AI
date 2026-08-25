from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from app.domain.actions import CompensationStatus
from app.schemas.base import ApiModel


class CompensationCreate(ApiModel):
    parameters: dict[str, JsonValue]
    idempotency_key: str = Field(min_length=8, max_length=128)
    expires_in_seconds: int = Field(default=3600, ge=60, le=86400)


class CompensationDecision(ApiModel):
    decision: Literal["approve", "reject"]
    expected_version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=2000)


class CompensationDispatch(ApiModel):
    expected_version: int = Field(ge=1)


class CompensationEscalate(ApiModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class CompensationResponse(ApiModel):
    id: UUID
    action_request_id: UUID
    verification_id: UUID
    environment_id: UUID
    incident_id: UUID
    resource_id: UUID
    capability: str
    parameters: dict[str, JsonValue]
    status: CompensationStatus
    idempotency_key: str
    requested_by: str
    decided_by: str | None
    decision_comment: str | None
    expires_at: datetime
    decided_at: datetime | None
    escalation_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class CompensationExecutionResponse(ApiModel):
    id: UUID
    compensation_request_id: UUID
    status: CompensationStatus
    lease_expires_at: datetime | None
    result_summary: str | None
    error_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class RunnerCompensationExecutionResponse(CompensationExecutionResponse):
    runner_id: UUID
    runner_fencing_token: int | None
    execution_fencing_token: int
    resource_fencing_token: int
