from datetime import datetime
from uuid import UUID

from app.schemas.base import ApiModel


class OutboxStatusResponse(ApiModel):
    pending_count: int
    dead_letter_count: int
    oldest_pending_at: datetime | None
    oldest_pending_age_seconds: float | None


class OutboxDeadLetterResponse(ApiModel):
    event_id: UUID
    sequence: int
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    incident_id: UUID
    occurred_at: datetime
    publish_attempts: int
    dead_lettered_at: datetime
    last_error: str | None
    last_status_code: int | None


class OutboxReplayResponse(ApiModel):
    event_id: UUID
    status: str
    next_attempt_at: datetime
