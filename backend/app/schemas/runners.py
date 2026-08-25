from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from app.domain.runners import RunnerStatus
from app.schemas.base import ApiModel

_PROHIBITED_ACTION_PARTS = {"command", "exec", "run_shell", "shell"}


class ConnectorCapability(ApiModel):
    connector: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    contract_version: str = Field(pattern=r"^\d+\.\d+(?:\.\d+)?$")
    observe: list[str] = Field(default_factory=list, max_length=200)
    actions: list[str] = Field(default_factory=list, max_length=100)
    unsupported: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("actions")
    @classmethod
    def reject_arbitrary_execution(cls, actions: list[str]) -> list[str]:
        for action in actions:
            parts = {part.lower() for part in action.replace("-", "_").split(".")}
            if parts & _PROHIBITED_ACTION_PARTS:
                raise ValueError("Arbitrary command execution capabilities are prohibited")
        return actions


class RunnerRegisterRequest(ApiModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,149}$")
    software_version: str = Field(min_length=1, max_length=50)
    environment_id: UUID | None = None
    capabilities: list[ConnectorCapability] = Field(default_factory=list, max_length=100)
    labels: dict[str, str] = Field(default_factory=dict)


class RunnerHeartbeatRequest(ApiModel):
    heartbeat_id: UUID
    software_version: str | None = Field(default=None, min_length=1, max_length=50)
    capabilities: list[ConnectorCapability] | None = Field(default=None, max_length=100)
    labels: dict[str, str] | None = None


class RunnerResponse(ApiModel):
    id: UUID
    name: str
    status: RunnerStatus
    software_version: str
    environment_id: UUID | None
    capabilities: list[dict[str, Any]]
    labels: dict[str, str]
    token_expires_at: datetime
    last_seen_at: datetime
    lease_expires_at: datetime
    version: int
    created_at: datetime
    updated_at: datetime


class RunnerRegistrationResponse(RunnerResponse):
    access_token: str
    fencing_token: int


class RunnerHeartbeatResponse(ApiModel):
    runner_id: UUID
    status: RunnerStatus
    lease_expires_at: datetime
    fencing_token: int
    version: int
    duplicate: bool
    access_token: str | None = None
    token_expires_at: datetime
