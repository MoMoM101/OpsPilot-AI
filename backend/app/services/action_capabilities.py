from dataclasses import dataclass
from typing import Literal

from app.domain.plans import PlanStepRisk
from app.schemas.action_capabilities import (
    ActionCapabilityCatalogResponse,
    ActionCapabilityResponse,
    ActionCompensationDefinitionResponse,
    ActionParameterDefinitionResponse,
    ActionVerificationDefinitionResponse,
)


@dataclass(frozen=True, slots=True)
class ActionCapabilityDefinition:
    capability: str
    parameter_key: str
    availability: Literal["available", "reserved"]
    effect: Literal["mutation", "observation"]
    recommended_risk: PlanStepRisk
    execution_connector: str | None = None
    verification_operation: str | None = None
    verification_parameter_key: str | None = None
    compensation_mode: Literal[
        "manual_escalation", "not_applicable", "unavailable"
    ] = "unavailable"


ACTION_CAPABILITY_DEFINITIONS = (
    ActionCapabilityDefinition(
        capability="container.restart",
        parameter_key="containerId",
        availability="available",
        effect="mutation",
        recommended_risk=PlanStepRisk.MEDIUM,
        execution_connector="docker",
        verification_operation="docker.container_health",
        verification_parameter_key="containerId",
        compensation_mode="manual_escalation",
    ),
    ActionCapabilityDefinition(
        capability="health.check",
        parameter_key="target",
        availability="available",
        effect="observation",
        recommended_risk=PlanStepRisk.READ_ONLY,
        execution_connector="docker",
        verification_operation="docker.container_health",
        verification_parameter_key="containerId",
        compensation_mode="not_applicable",
    ),
    ActionCapabilityDefinition(
        capability="service.reload",
        parameter_key="serviceName",
        availability="reserved",
        effect="mutation",
        recommended_risk=PlanStepRisk.MEDIUM,
    ),
    ActionCapabilityDefinition(
        capability="traffic_probe.pause",
        parameter_key="probeId",
        availability="reserved",
        effect="mutation",
        recommended_risk=PlanStepRisk.LOW,
    ),
    ActionCapabilityDefinition(
        capability="traffic_probe.resume",
        parameter_key="probeId",
        availability="reserved",
        effect="mutation",
        recommended_risk=PlanStepRisk.LOW,
    ),
)

AVAILABLE_ACTION_CAPABILITIES = frozenset(
    definition.capability
    for definition in ACTION_CAPABILITY_DEFINITIONS
    if definition.availability == "available"
)

_DEFINITIONS_BY_CAPABILITY = {
    definition.capability: definition for definition in ACTION_CAPABILITY_DEFINITIONS
}


def action_capability_definition(capability: str) -> ActionCapabilityDefinition | None:
    return _DEFINITIONS_BY_CAPABILITY.get(capability)


def action_capability_catalog() -> ActionCapabilityCatalogResponse:
    return ActionCapabilityCatalogResponse(
        capabilities=[_response(definition) for definition in ACTION_CAPABILITY_DEFINITIONS]
    )


def _response(definition: ActionCapabilityDefinition) -> ActionCapabilityResponse:
    verification = None
    if (
        definition.execution_connector is not None
        and definition.verification_operation is not None
        and definition.verification_parameter_key is not None
    ):
        verification = ActionVerificationDefinitionResponse(
            connector=definition.execution_connector,
            operation=definition.verification_operation,
            action_parameter_key=definition.parameter_key,
            verification_parameter_key=definition.verification_parameter_key,
        )
    return ActionCapabilityResponse(
        capability=definition.capability,
        availability=definition.availability,
        effect=definition.effect,
        recommended_risk=definition.recommended_risk,
        execution_connector=definition.execution_connector,
        parameter=ActionParameterDefinitionResponse(key=definition.parameter_key),
        verification=verification,
        compensation=ActionCompensationDefinitionResponse(mode=definition.compensation_mode),
    )
