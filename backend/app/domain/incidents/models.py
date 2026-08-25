from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class IncidentStatus(StrEnum):
    DETECTED = "DETECTED"
    CORRELATING = "CORRELATING"
    INVESTIGATING = "INVESTIGATING"
    DIAGNOSED = "DIAGNOSED"
    PLANNING = "PLANNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    OBSERVABILITY_LOST = "OBSERVABILITY_LOST"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    MITIGATED_NOT_RESOLVED = "MITIGATED_NOT_RESOLVED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class Incident:
    id: UUID
    title: str
    status: IncidentStatus
    severity: Severity
    resource_id: UUID
    owner: str | None
    version: int
    created_at: datetime
    updated_at: datetime
