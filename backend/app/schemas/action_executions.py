from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from app.domain.actions import ActionRequestStatus
from app.schemas.base import ApiModel
from app.schemas.compensations import RunnerCompensationExecutionResponse


class ActionExecutionResponse(ApiModel):
    id: UUID
    action_request_id: UUID
    status: ActionRequestStatus
    lease_expires_at: datetime | None
    result_summary: str | None
    error_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class RunnerActionExecutionResponse(ActionExecutionResponse):
    runner_id: UUID
    runner_fencing_token: int | None
    execution_fencing_token: int
    resource_fencing_token: int


class RunnerActionClaimRequest(ApiModel):
    runner_fencing_token: int = Field(ge=1)


class RunnerActionExecution(ApiModel):
    execution_kind: Literal["action", "compensation"] = "action"
    execution_id: UUID
    action_id: UUID
    compensation_id: UUID | None = None
    incident_id: UUID
    resource_id: UUID
    capability: str
    parameters: dict[str, JsonValue]
    verification_criteria: list[str]
    rollback_capability: str | None
    execution_fencing_token: int
    resource_fencing_token: int
    lease_expires_at: datetime


class RunnerActionClaimResponse(ApiModel):
    execution: RunnerActionExecution | None


class RunnerActionLeaseRequest(ApiModel):
    execution_fencing_token: int = Field(ge=1)
    resource_fencing_token: int = Field(ge=1)


class RunnerActionCompleteRequest(RunnerActionLeaseRequest):
    completion_id: UUID
    status: Literal["succeeded", "failed"]
    summary: str = Field(min_length=1, max_length=2000)
    error_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_error_code(self) -> "RunnerActionCompleteRequest":
        if self.status == "failed" and not self.error_code:
            raise ValueError("errorCode is required for failed Actions")
        return self


class RunnerActionCompleteResponse(ApiModel):
    execution: RunnerActionExecutionResponse | RunnerCompensationExecutionResponse
    duplicate: bool


class ActionReconcileRequest(ApiModel):
    expected_version: int = Field(ge=1)
    outcome: Literal["succeeded", "failed"]
    summary: str = Field(min_length=1, max_length=2000)
    error_code: str | None = Field(default=None, max_length=100)
