from typing import Literal

from app.domain.plans import PlanStepRisk
from app.schemas.base import ApiModel


class ActionParameterDefinitionResponse(ApiModel):
    key: str
    value_type: Literal["string"] = "string"
    required: bool = True
    min_length: int = 1
    max_length: int = 300
    secret: bool = False


class ActionVerificationDefinitionResponse(ApiModel):
    connector: str
    operation: str
    action_parameter_key: str
    verification_parameter_key: str


class ActionCompensationDefinitionResponse(ApiModel):
    supported: bool = False
    mode: Literal["manual_escalation", "not_applicable", "unavailable"]
    capability: str | None = None


class ActionCapabilityResponse(ApiModel):
    capability: str
    availability: Literal["available", "reserved"]
    effect: Literal["mutation", "observation"]
    recommended_risk: PlanStepRisk
    execution_connector: str | None
    approval_mode: Literal["policy"] = "policy"
    verification_criteria_required: bool = True
    parameter: ActionParameterDefinitionResponse
    verification: ActionVerificationDefinitionResponse | None
    compensation: ActionCompensationDefinitionResponse


class ActionCapabilityCatalogResponse(ApiModel):
    contract_version: str = "1.0"
    capabilities: list[ActionCapabilityResponse]
