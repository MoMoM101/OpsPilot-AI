import json
from datetime import datetime
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from app.domain.actions import ActionRequestStatus
from app.schemas.base import ApiModel


class ActionRequestCreate(ApiModel):
    policy_decision_id: UUID
    approval_id: UUID | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    verification_criteria: list[str] = Field(min_length=1, max_length=20)
    rollback_capability: str | None = Field(default=None, min_length=1, max_length=150)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_payload_size(self) -> "ActionRequestCreate":
        encoded = json.dumps(self.parameters, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 16384:
            raise ValueError("Action parameters exceed 16 KiB")
        if any(not item.strip() or len(item) > 500 for item in self.verification_criteria):
            raise ValueError("verificationCriteria entries must contain 1 to 500 characters")
        return self


class ActionRequestCancel(ApiModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class ActionRequestResponse(ApiModel):
    id: UUID
    policy_decision_id: UUID
    approval_id: UUID | None
    environment_id: UUID
    incident_id: UUID
    resource_id: UUID
    capability: str
    status: ActionRequestStatus
    parameters: dict[str, JsonValue]
    verification_criteria: list[str]
    rollback_capability: str | None
    idempotency_key: str
    created_by: str
    cancelled_by: str | None
    cancellation_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class ActionRequestCreateResponse(ApiModel):
    action: ActionRequestResponse
    replayed: bool
