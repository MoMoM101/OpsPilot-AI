from dataclasses import dataclass

from app.domain.plans.models import PlanStepStatus

_ALLOWED_TRANSITIONS: dict[PlanStepStatus, frozenset[PlanStepStatus]] = {
    PlanStepStatus.PENDING: frozenset(
        {PlanStepStatus.RUNNING, PlanStepStatus.SKIPPED, PlanStepStatus.BLOCKED}
    ),
    PlanStepStatus.RUNNING: frozenset(
        {PlanStepStatus.COMPLETED, PlanStepStatus.FAILED, PlanStepStatus.BLOCKED}
    ),
    PlanStepStatus.FAILED: frozenset({PlanStepStatus.PENDING, PlanStepStatus.SKIPPED}),
    PlanStepStatus.BLOCKED: frozenset({PlanStepStatus.PENDING, PlanStepStatus.SKIPPED}),
    PlanStepStatus.COMPLETED: frozenset(),
    PlanStepStatus.SKIPPED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class PlanStepTransitionError(ValueError):
    current: PlanStepStatus
    target: PlanStepStatus

    def __str__(self) -> str:
        return f"Plan step cannot transition from {self.current} to {self.target}"


def transition_plan_step(current: PlanStepStatus, target: PlanStepStatus) -> PlanStepStatus:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise PlanStepTransitionError(current=current, target=target)
    return target
