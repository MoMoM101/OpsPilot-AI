from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.investigations import (
    InvestigationHITLSubjectType,
    InvestigationHITLWaitStatus,
    InvestigationRunStatus,
)
from app.schemas.base import ApiModel


class InvestigationRunCreate(ApiModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    graph_version: str = Field(default="graph-v2", min_length=1, max_length=50)
    max_iterations: int = Field(default=20, ge=1, le=200)
    max_model_requests: int = Field(default=20, ge=1, le=200)


class InvestigationRunTransition(ApiModel):
    target: InvestigationRunStatus
    expected_version: int = Field(ge=1)
    error_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_failure_code(self) -> "InvestigationRunTransition":
        if self.target == InvestigationRunStatus.FAILED and not self.error_code:
            raise ValueError("errorCode is required when an investigation run fails")
        if self.target != InvestigationRunStatus.FAILED and self.error_code is not None:
            raise ValueError("errorCode is only valid for failed investigation runs")
        return self


class InvestigationRunCancel(ApiModel):
    expected_version: int = Field(ge=1)


class InvestigationCheckpointCreate(ApiModel):
    node_execution_id: str = Field(min_length=8, max_length=128)
    expected_run_version: int = Field(ge=1)
    node: str = Field(min_length=1, max_length=100)
    iteration: int = Field(ge=0, le=200)
    plan_step_id: UUID | None = None
    hypothesis_ids: list[UUID] = Field(default_factory=list, max_length=100)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=200)
    completed_node_keys: list[str] = Field(default_factory=list, max_length=200)
    no_progress_count: int = Field(default=0, ge=0, le=200)
    progressed: bool = True
    next_action: str | None = Field(default=None, max_length=50)
    model_requests: int = Field(default=0, ge=0, le=20)
    model_input_tokens: int = Field(default=0, ge=0)
    model_output_tokens: int = Field(default=0, ge=0)
    output_summary: str | None = Field(default=None, max_length=2000)


class InvestigationHITLWaitCreate(ApiModel):
    checkpoint_id: UUID
    subject_type: InvestigationHITLSubjectType
    subject_id: UUID
    expected_run_version: int = Field(ge=1)


class InvestigationHITLWaitResponse(ApiModel):
    id: UUID
    run_id: UUID
    incident_id: UUID
    checkpoint_id: UUID
    subject_type: InvestigationHITLSubjectType
    subject_id: UUID
    status: InvestigationHITLWaitStatus
    outcome: str | None
    resolved_at: datetime | None
    resumed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class InvestigationHITLWaitWriteResponse(ApiModel):
    wait: InvestigationHITLWaitResponse
    duplicate: bool


class InvestigationRunResponse(ApiModel):
    id: UUID
    incident_id: UUID
    thread_id: UUID
    status: InvestigationRunStatus
    graph_version: str
    current_node: str | None
    iteration_count: int
    max_iterations: int
    last_checkpoint_sequence: int
    started_at: datetime | None
    completed_at: datetime | None
    last_error_code: str | None
    runtime_attempt: int
    model_request_limit: int
    model_requests_used: int
    model_input_tokens_used: int
    model_output_tokens_used: int
    version: int
    created_at: datetime
    updated_at: datetime


class InvestigationCheckpointResponse(ApiModel):
    id: UUID
    run_id: UUID
    sequence: int
    node_execution_id: str
    node: str
    graph_version: str
    iteration: int
    plan_step_id: UUID | None
    hypothesis_ids: list[UUID]
    evidence_ids: list[UUID]
    completed_node_keys: list[str]
    no_progress_count: int
    progressed: bool
    next_action: str | None
    model_requests: int
    model_input_tokens: int
    model_output_tokens: int
    output_summary: str | None
    created_at: datetime


class InvestigationCheckpointWriteResponse(ApiModel):
    checkpoint: InvestigationCheckpointResponse
    duplicate: bool
    run_version: int


class InvestigationGraphNodeResponse(ApiModel):
    key: str
    phase: str
    side_effecting: bool
    description: str


class InvestigationGraphResponse(ApiModel):
    version: str
    entry_node: str
    nodes: list[InvestigationGraphNodeResponse]
