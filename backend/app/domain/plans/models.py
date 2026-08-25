from enum import StrEnum


class PlanStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class PlanStepType(StrEnum):
    OBSERVE = "observe"
    ANALYZE = "analyze"
    EXPERIMENT = "experiment"
    REMEDIATE = "remediate"
    VERIFY = "verify"
    HUMAN = "human"


class PlanStepRisk(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlanStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
