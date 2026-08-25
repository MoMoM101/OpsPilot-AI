from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.schemas.base import ApiModel


class EvidenceResponse(ApiModel):
    id: UUID
    incident_id: UUID
    resource_id: UUID | None
    evidence_type: str
    source: str
    summary: str
    content_hash: str
    redacted: bool
    observed_from: datetime | None
    observed_to: datetime | None
    collected_at: datetime | None
    collection_status: Literal["succeeded", "partial", "failed"]
    time_confidence: Literal["runner_reported", "source_timestamp", "control_plane"]
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime
