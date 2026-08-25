from app.domain.investigations.models import InvestigationRunStatus

_ALLOWED_TRANSITIONS: dict[
    InvestigationRunStatus,
    frozenset[InvestigationRunStatus],
] = {
    InvestigationRunStatus.QUEUED: frozenset(
        {InvestigationRunStatus.RUNNING, InvestigationRunStatus.CANCELLED}
    ),
    InvestigationRunStatus.RUNNING: frozenset(
        {
            InvestigationRunStatus.PAUSED,
            InvestigationRunStatus.COMPLETED,
            InvestigationRunStatus.FAILED,
            InvestigationRunStatus.CANCELLED,
        }
    ),
    InvestigationRunStatus.PAUSED: frozenset(
        {
            InvestigationRunStatus.RUNNING,
            InvestigationRunStatus.FAILED,
            InvestigationRunStatus.CANCELLED,
        }
    ),
    InvestigationRunStatus.COMPLETED: frozenset(),
    InvestigationRunStatus.FAILED: frozenset(),
    InvestigationRunStatus.CANCELLED: frozenset(),
}


def transition_investigation_run(
    current: InvestigationRunStatus,
    target: InvestigationRunStatus,
) -> InvestigationRunStatus:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Investigation run cannot transition from {current} to {target}")
    return target
