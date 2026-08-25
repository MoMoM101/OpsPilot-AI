from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import ApiModel


class DemoStatusResponse(ApiModel):
    available: bool
    reason_code: Literal["DEMO_DISABLED", "PRODUCTION_DISABLED"] | None
    status: Literal["unavailable", "inactive", "active", "drifted"]
    manifest_version: int
    generation: int
    environment_id: UUID | None
    resource_ids: list[UUID]
    incident_ids: list[UUID]


class DemoInitializeResponse(DemoStatusResponse):
    replayed: bool


class DemoCleanupRequest(ApiModel):
    expected_generation: int = Field(ge=1)


class DemoCleanupResponse(DemoStatusResponse):
    replayed: bool
    deleted_incident_count: int
