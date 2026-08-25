from datetime import datetime
from typing import Any
from uuid import UUID

from app.schemas.base import ApiModel


class AgentEvent(ApiModel):
    id: UUID
    sequence: int
    type: str
    incident_id: UUID
    trace_id: UUID
    version: int
    occurred_at: datetime
    payload: dict[str, Any]
