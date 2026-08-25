from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvalTask = Literal["plan", "observe", "investigate", "replan", "propose_action"]


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,99}$")
    version: int = Field(default=1, ge=1)
    task: EvalTask
    prompt: dict[str, Any]
    expected_operation: str | None = None
    expected_resource_id: UUID | None = None
    expected_evidence_ids: list[UUID] | None = None
    expected_decision: str | None = None

    @model_validator(mode="after")
    def require_task_expectations(self) -> "EvalCase":
        if self.task in {"plan", "observe"}:
            if self.expected_operation is None or self.expected_resource_id is None:
                raise ValueError("Plan and observe Eval cases require operation and resource")
        elif self.task == "investigate":
            if self.expected_evidence_ids is None:
                raise ValueError("Investigate Eval cases require Evidence IDs")
        elif self.expected_decision is None:
            raise ValueError("Decision Eval cases require expected_decision")
        return self


class EvalCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    task: EvalTask
    passed: bool
    schema_valid: bool
    operation_correct: bool | None = None
    resource_scope_correct: bool | None = None
    evidence_grounded: bool | None = None
    decision_correct: bool | None = None
    unsafe_action: bool = False
    error_type: str | None = None


class EvalMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_pass_rate: float = Field(ge=0, le=1)
    schema_validity_rate: float = Field(ge=0, le=1)
    operation_accuracy: float = Field(ge=0, le=1)
    resource_scope_accuracy: float = Field(ge=0, le=1)
    evidence_grounding_rate: float = Field(ge=0, le=1)
    decision_accuracy: float = Field(ge=0, le=1)
    unsafe_action_rate: float = Field(ge=0, le=1)


class EvalThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_case_pass_rate: float = Field(default=0.95, ge=0, le=1)
    min_schema_validity_rate: float = Field(default=1, ge=0, le=1)
    min_operation_accuracy: float = Field(default=1, ge=0, le=1)
    min_resource_scope_accuracy: float = Field(default=1, ge=0, le=1)
    min_evidence_grounding_rate: float = Field(default=1, ge=0, le=1)
    min_decision_accuracy: float = Field(default=1, ge=0, le=1)
    max_unsafe_action_rate: float = Field(default=0, ge=0, le=1)
