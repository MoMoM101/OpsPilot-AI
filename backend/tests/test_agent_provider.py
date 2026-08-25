import asyncio
from uuid import uuid4

import pytest
from pydantic_ai.models.test import TestModel

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.services.actions import ActionRequestService
from app.services.agent_provider import (
    ActionProposal,
    ActionProposalOutput,
    ObservationProposal,
    ObservationProposalOutput,
    PlannerOutput,
    PydanticAIAgentProvider,
    ReplannerOutput,
)


def test_pydantic_ai_provider_validates_structured_planner_output() -> None:
    resource_id = uuid4()
    provider = PydanticAIAgentProvider(
        TestModel(
            custom_output_args={
                "objective": "Identify the failing dependency",
                "steps": [
                    {
                        "title": "Inspect service health",
                        "objective": "Collect bounded health evidence",
                        "kind": "observe",
                        "dependencies": [],
                        "resource_scope": [str(resource_id)],
                        "allowed_capabilities": ["http.probe"],
                        "expected_evidence": ["HTTP status and latency"],
                        "success_criteria": ["Health result is captured"],
                        "risk": "read_only",
                    }
                ],
                "max_tool_calls": 5,
                "max_duration_seconds": 600,
                "summary": "A single bounded observation is sufficient",
            }
        )
    )

    result = asyncio.run(provider.plan("Sanitized incident context"))

    assert isinstance(result.output, PlannerOutput)
    assert result.output.steps[0].resource_scope == [resource_id]
    assert result.requests == 1
    assert result.input_tokens >= 0
    assert result.output_tokens >= 0


def test_pydantic_ai_provider_uses_a_single_bounded_connection_probe() -> None:
    provider = PydanticAIAgentProvider(
        TestModel(custom_output_args={"status": "ok"}),
        request_limit=5,
    )

    result = asyncio.run(provider.check_connection())

    assert result.output.status == "ok"
    assert result.requests == 1


def test_pydantic_ai_provider_returns_typed_replan_decision() -> None:
    provider = PydanticAIAgentProvider(
        TestModel(
            custom_output_args={
                "action": "pause",
                "progressed": False,
                "reason": "No current evidence is available",
            }
        )
    )

    result = asyncio.run(provider.replan("Evidence references: []"))

    assert result.output == ReplannerOutput(
        action="pause",
        progressed=False,
        reason="No current evidence is available",
    )


def test_pydantic_ai_provider_returns_parameter_free_observation_proposal() -> None:
    resource_id = uuid4()
    provider = PydanticAIAgentProvider(
        TestModel(
            custom_output_args={
                "action": "observe",
                "proposal": {
                    "resource_id": str(resource_id),
                    "operation": "http.probe",
                    "purpose": "Distinguish process health from business readiness",
                },
                "reason": "A bounded business probe is required",
            }
        )
    )

    result = asyncio.run(provider.observe("Sanitized plan and resource allowlist"))

    assert result.output == ObservationProposalOutput(
        action="observe",
        proposal=ObservationProposal(
            resource_id=resource_id,
            operation="http.probe",
            purpose="Distinguish process health from business readiness",
        ),
        reason="A bounded business probe is required",
    )


def test_observation_proposal_rejects_model_generated_parameters() -> None:
    with pytest.raises(ValueError):
        ObservationProposal.model_validate(
            {
                "resourceId": str(uuid4()),
                "operation": "http.probe",
                "purpose": "Probe service",
                "parameters": {"url": "http://untrusted.example"},
            }
        )


def test_agent_runtime_requires_model_configuration_when_enabled() -> None:
    with pytest.raises(ValueError, match="Agent model name and API key"):
        Settings(agent_runtime_enabled=True)


@pytest.mark.parametrize(
    ("action", "proposal"),
    [("propose", None), ("none", {"resource_id": str(uuid4())})],
)
def test_action_output_requires_proposal_only_for_propose(
    action: str, proposal: object | None
) -> None:
    with pytest.raises(ValueError):
        ActionProposalOutput.model_validate(
            {"action": action, "proposal": proposal, "reason": "bounded decision"}
        )


@pytest.mark.parametrize(
    ("action", "proposal"),
    [("observe", None), ("none", {"resource_id": str(uuid4())})],
)
def test_observation_output_requires_proposal_only_for_observe(
    action: str, proposal: object | None
) -> None:
    with pytest.raises(ValueError):
        ObservationProposalOutput.model_validate(
            {"action": action, "proposal": proposal, "reason": "bounded decision"}
        )


def test_action_proposal_rejects_top_level_command_injection() -> None:
    with pytest.raises(ValueError, match="extra_forbidden"):
        ActionProposal.model_validate(
            {
                "resource_id": str(uuid4()),
                "capability": "container.restart",
                "parameters": {"containerId": "api"},
                "verification_criteria": ["service recovers"],
                "risk": "medium",
                "command": "docker restart --privileged api",
            }
        )


@pytest.mark.parametrize(
    ("capability", "parameters"),
    [
        ("shell.execute", {"command": "id"}),
        ("container.restart", {"containerId": "api", "command": "id"}),
    ],
)
def test_server_action_allowlist_rejects_tool_bypass_payloads(
    capability: str, parameters: dict[str, object]
) -> None:
    with pytest.raises(ApplicationError):
        ActionRequestService.validate_capability_parameters(capability, parameters)
