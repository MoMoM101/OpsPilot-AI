from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel


class LabScenarioResponse(ApiModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    status: Literal["ready", "active", "unavailable"]
    version: int = Field(ge=1)
    active: bool
    supported: bool


class LabScenarioMutationRequest(ApiModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class LabScenarioMutationResponse(ApiModel):
    scenario: LabScenarioResponse
    replayed: bool
