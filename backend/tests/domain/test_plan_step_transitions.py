import pytest

from app.domain.plans import PlanStepStatus, PlanStepTransitionError, transition_plan_step


def test_plan_step_can_complete_after_running() -> None:
    running = transition_plan_step(PlanStepStatus.PENDING, PlanStepStatus.RUNNING)
    completed = transition_plan_step(running, PlanStepStatus.COMPLETED)
    assert completed is PlanStepStatus.COMPLETED


def test_completed_plan_step_cannot_restart() -> None:
    with pytest.raises(PlanStepTransitionError):
        transition_plan_step(PlanStepStatus.COMPLETED, PlanStepStatus.RUNNING)
