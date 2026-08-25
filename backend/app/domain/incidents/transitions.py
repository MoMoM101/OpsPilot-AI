from dataclasses import dataclass

from app.domain.incidents.models import IncidentStatus

_ALLOWED_TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IncidentStatus.DETECTED: frozenset({IncidentStatus.CORRELATING, IncidentStatus.CANCELLED}),
    IncidentStatus.CORRELATING: frozenset(
        {IncidentStatus.INVESTIGATING, IncidentStatus.NEEDS_HUMAN, IncidentStatus.FAILED}
    ),
    IncidentStatus.INVESTIGATING: frozenset(
        {
            IncidentStatus.DIAGNOSED,
            IncidentStatus.OBSERVABILITY_LOST,
            IncidentStatus.NEEDS_HUMAN,
            IncidentStatus.FAILED,
        }
    ),
    IncidentStatus.DIAGNOSED: frozenset({IncidentStatus.PLANNING, IncidentStatus.NEEDS_HUMAN}),
    IncidentStatus.PLANNING: frozenset(
        {
            IncidentStatus.WAITING_APPROVAL,
            IncidentStatus.REMEDIATING,
            IncidentStatus.NEEDS_HUMAN,
        }
    ),
    IncidentStatus.WAITING_APPROVAL: frozenset(
        {IncidentStatus.REMEDIATING, IncidentStatus.CANCELLED, IncidentStatus.NEEDS_HUMAN}
    ),
    IncidentStatus.REMEDIATING: frozenset(
        {IncidentStatus.VERIFYING, IncidentStatus.NEEDS_HUMAN, IncidentStatus.FAILED}
    ),
    IncidentStatus.VERIFYING: frozenset(
        {
            IncidentStatus.RESOLVED,
            IncidentStatus.MITIGATED_NOT_RESOLVED,
            IncidentStatus.INVESTIGATING,
            IncidentStatus.NEEDS_HUMAN,
        }
    ),
    IncidentStatus.RESOLVED: frozenset({IncidentStatus.CLOSED, IncidentStatus.INVESTIGATING}),
    IncidentStatus.OBSERVABILITY_LOST: frozenset(
        {IncidentStatus.INVESTIGATING, IncidentStatus.NEEDS_HUMAN, IncidentStatus.CANCELLED}
    ),
    IncidentStatus.MITIGATED_NOT_RESOLVED: frozenset(
        {IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED, IncidentStatus.NEEDS_HUMAN}
    ),
    IncidentStatus.NEEDS_HUMAN: frozenset(
        {IncidentStatus.INVESTIGATING, IncidentStatus.CANCELLED, IncidentStatus.FAILED}
    ),
    IncidentStatus.CLOSED: frozenset(),
    IncidentStatus.FAILED: frozenset(),
    IncidentStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class IncidentTransitionError(ValueError):
    current: IncidentStatus
    target: IncidentStatus

    def __str__(self) -> str:
        return f"Incident cannot transition from {self.current} to {self.target}"


def transition_incident(current: IncidentStatus, target: IncidentStatus) -> IncidentStatus:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise IncidentTransitionError(current=current, target=target)
    return target
