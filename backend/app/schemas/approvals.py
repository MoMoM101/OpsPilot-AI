from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.approvals import ApprovalDecision, ApprovalStatus
from app.schemas.base import ApiModel

type ApprovalParameter = str | int | float | bool | None


class ApprovalCreate(ApiModel):
    policy_decision_id: UUID
    parameters: dict[str, ApprovalParameter] = Field(default_factory=dict)
    editable_parameter_keys: list[str] = Field(default_factory=list, max_length=50)
    expires_in_seconds: int = Field(default=3600, ge=60, le=86400)

    @model_validator(mode="after")
    def validate_editable_keys(self) -> "ApprovalCreate":
        keys = self.editable_parameter_keys
        if len(set(keys)) != len(keys) or not set(keys).issubset(self.parameters):
            raise ValueError("editableParameterKeys must be unique keys present in parameters")
        return self


class ApprovalDecisionRequest(ApiModel):
    decision: ApprovalDecision
    expected_version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=2000)
    parameter_edits: dict[str, ApprovalParameter] = Field(default_factory=dict)


class ApprovalResponse(ApiModel):
    id: UUID
    policy_decision_id: UUID
    environment_id: UUID
    incident_id: UUID
    resource_id: UUID
    capability: str
    status: ApprovalStatus
    requested_by: str
    decided_by: str | None
    expires_at: datetime
    decided_at: datetime | None
    decision_comment: str | None
    parameters: dict[str, ApprovalParameter]
    editable_parameter_keys: list[str]
    version: int
    created_at: datetime
    updated_at: datetime
