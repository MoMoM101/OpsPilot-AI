from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.plans import PlanStepRisk
from app.services.action_proposals import ActionProposalInput, ActionProposalService


@pytest.mark.asyncio
async def test_proposal_rechecks_idempotency_after_run_lock() -> None:
    service = ActionProposalService(AsyncMock())
    run_id = uuid4()
    resource_id = uuid4()
    node_execution_id = "propose-action:0"
    proposal_input = ActionProposalInput(
        resource_id=resource_id,
        capability="container.restart",
        parameters={"containerId": "api"},
        verification_criteria=["container becomes healthy"],
        rollback_capability=None,
        risk=PlanStepRisk.MEDIUM,
    )
    existing = SimpleNamespace(
        resource_id=resource_id,
        capability="container.restart",
        parameters={"containerId": "api"},
        verification_criteria=["container becomes healthy"],
        rollback_capability=None,
        risk="medium",
    )
    service.proposals.get_by_execution = AsyncMock(side_effect=[None, existing])
    service.runs.get_run = AsyncMock(return_value=SimpleNamespace(id=run_id))

    result = await service.propose(
        run_id=run_id,
        node_execution_id=node_execution_id,
        input=proposal_input,
    )

    assert result.duplicate is True
    assert result.proposal is existing
    service.runs.get_run.assert_awaited_once_with(run_id, for_update=True)
    assert service.proposals.get_by_execution.await_count == 2
