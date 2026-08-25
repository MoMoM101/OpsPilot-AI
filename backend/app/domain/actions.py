from enum import StrEnum

SUPPORTED_ACTION_CAPABILITIES = frozenset(
    {
        "container.restart",
        "service.reload",
        "traffic_probe.pause",
        "traffic_probe.resume",
        "health.check",
    }
)


class ActionProposalStatus(StrEnum):
    PROPOSED = "proposed"
    DENIED = "denied"
    AWAITING_APPROVAL = "awaiting_approval"
    ACTION_READY = "action_ready"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ActionRequestStatus(StrEnum):
    READY = "ready"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    APPLIED = "applied"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    VERIFICATION_FAILED = "verification_failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    ESCALATED = "escalated"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class ActionVerificationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class CompensationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    ESCALATED = "escalated"
