from typing import Literal
from uuid import UUID

from app.schemas.base import ApiModel


class ConnectorAvailabilityResponse(ApiModel):
    status: Literal["ready", "partial", "offline", "not_configured", "incompatible"]
    configured_runner_count: int
    compatible_runner_count: int
    online_runner_count: int
    incompatible_runner_count: int
    ready_observe_operations: list[str]
    ready_action_operations: list[str]


class ConnectorCatalogItemResponse(ApiModel):
    connector: str
    contract_version: str
    setup_kind: Literal["built_in", "allowlist"]
    configuration_owner: Literal["runner"] = "runner"
    runner_setting_keys: list[str]
    prerequisites: list[str]
    supported_platforms: list[Literal["linux", "windows", "macos"]]
    observe_operations: list[str]
    action_operations: list[str]
    availability: ConnectorAvailabilityResponse


class ConnectorCatalogResponse(ApiModel):
    environment_id: UUID | None
    connectors: list[ConnectorCatalogItemResponse]
