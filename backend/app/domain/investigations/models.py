from enum import StrEnum


class InvestigationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvestigationHITLSubjectType(StrEnum):
    APPROVAL = "approval"
    COMPENSATION = "compensation"


class InvestigationHITLWaitStatus(StrEnum):
    WAITING = "waiting"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class InvestigationObservationWaitStatus(StrEnum):
    WAITING = "waiting"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
