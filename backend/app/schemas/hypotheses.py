from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.hypotheses import HypothesisStatus
from app.schemas.base import ApiModel


class HypothesisCreate(ApiModel):
    summary: str = Field(min_length=1, max_length=500)
    confidence: int = Field(ge=0, le=100)
    supporting_evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    contradicting_evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)


class HypothesisUpdate(ApiModel):
    expected_version: int = Field(ge=1)
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    confidence: int | None = Field(default=None, ge=0, le=100)
    status: HypothesisStatus | None = None
    supporting_evidence_ids: list[UUID] | None = Field(default=None, max_length=100)
    contradicting_evidence_ids: list[UUID] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_change(self) -> "HypothesisUpdate":
        if all(
            value is None
            for value in (
                self.summary,
                self.confidence,
                self.status,
                self.supporting_evidence_ids,
                self.contradicting_evidence_ids,
            )
        ):
            raise ValueError("At least one hypothesis field must be updated")
        return self


class HypothesisSummary(ApiModel):
    id: UUID
    ordinal: int
    summary: str
    confidence: int
    status: HypothesisStatus


class HypothesisResponse(HypothesisSummary):
    incident_id: UUID
    supporting_evidence_ids: list[UUID]
    contradicting_evidence_ids: list[UUID]
    version: int
    created_at: datetime
    updated_at: datetime
