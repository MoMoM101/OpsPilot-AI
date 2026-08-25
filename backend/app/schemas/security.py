from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.security import PrincipalKind, PrincipalRole
from app.schemas.base import ApiModel


class PrincipalCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    kind: PrincipalKind = PrincipalKind.USER
    role: PrincipalRole
    environment_ids: list[UUID] = Field(default_factory=list, max_length=100)
    unrestricted_environments: bool = False

    @model_validator(mode="after")
    def validate_scope(self) -> "PrincipalCreate":
        if self.unrestricted_environments and self.environment_ids:
            raise ValueError("Unrestricted principals cannot also declare environmentIds")
        if self.role == PrincipalRole.RUNTIME and self.kind != PrincipalKind.SERVICE:
            raise ValueError("Runtime principals must use service kind")
        return self


class PrincipalResponse(ApiModel):
    id: UUID
    name: str
    kind: PrincipalKind
    role: PrincipalRole
    environment_ids: list[UUID]
    unrestricted_environments: bool
    active: bool
    token_issued_at: datetime
    token_expires_at: datetime
    created_at: datetime
    updated_at: datetime


class PrincipalCreateResponse(PrincipalResponse):
    access_token: str


class PrincipalTokenRotateResponse(ApiModel):
    principal_id: UUID
    access_token: str
    token_issued_at: datetime
    token_expires_at: datetime


class BrowserSessionCreate(ApiModel):
    access_token: str = Field(min_length=20, max_length=4096)


class BrowserSessionResponse(ApiModel):
    principal: "PrincipalSessionResponse"
    csrf_token: str
    expires_at: datetime
    absolute_expires_at: datetime


class AuditRecordResponse(ApiModel):
    id: UUID
    occurred_at: datetime
    actor_id: str
    actor_type: str
    actor_role: str
    method: str
    path: str
    status_code: int
    request_id: str | None
    trace_id: str | None
    action: str | None
    outcome: str | None
    error_code: str | None
    source_ip: str | None
    user_agent_hash: str | None


class PrincipalSessionResponse(ApiModel):
    id: UUID | None
    name: str
    kind: PrincipalKind
    role: PrincipalRole
    environment_ids: list[UUID]
    unrestricted_environments: bool
