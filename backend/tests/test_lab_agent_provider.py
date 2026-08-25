import json
from uuid import uuid4

import pytest

from app.services.lab_agent_provider import DeterministicLabAgentProvider


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "operation"),
    [
        ("RAG vector-store dependency is unreachable", "qdrant.health"),
        ("Document storage is locked", "sqlite.lock_status"),
        ("Embedding latency exceeded", "rag.business_health"),
        ("RAG business endpoint returns an error", "rag.business_health"),
        ("Vector-store cardinality is wrong", "qdrant.point_count"),
    ],
)
async def test_deterministic_lab_provider_selects_one_bounded_observation(
    title: str,
    operation: str,
) -> None:
    provider = DeterministicLabAgentProvider()
    resource_id = uuid4()
    prompt = json.dumps(
        {
            "incident": {
                "resourceId": str(resource_id),
                "untrustedData": {"title": title},
            }
        }
    )

    plan = await provider.plan(prompt)
    assert len(plan.output.steps) == 1
    assert plan.output.steps[0].allowed_capabilities == [operation]
    assert plan.output.steps[0].resource_scope == [resource_id]

    observation = await provider.observe(
        json.dumps(
            {
                "activePlanStep": {
                    "resourceIds": [str(resource_id)],
                    "allowedOperations": [operation],
                }
            }
        )
    )
    assert observation.output.proposal is not None
    assert observation.output.proposal.resource_id == resource_id
    assert observation.output.proposal.operation.value == operation


@pytest.mark.asyncio
async def test_deterministic_lab_provider_references_only_supplied_evidence() -> None:
    provider = DeterministicLabAgentProvider()
    evidence_id = uuid4()

    investigation = await provider.investigate(
        json.dumps({"evidence": [{"id": str(evidence_id)}]})
    )
    replan = await provider.replan(json.dumps({"evidence": [{"id": str(evidence_id)}]}))
    action = await provider.propose_action(json.dumps({}))

    assert investigation.output.evidence_ids == [evidence_id]
    assert investigation.output.hypotheses[0].supporting_evidence_ids == [evidence_id]
    assert replan.output.action == "finish"
    assert action.output.action == "none"
