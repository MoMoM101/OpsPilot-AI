from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import ApiModel


class ResourceLockTokenRequest(ApiModel):
    fencing_token: int = Field(ge=1)


class ResourceLockResponse(ApiModel):
    id: UUID
    environment_id: UUID
    resource_id: UUID
    action_request_id: UUID
    incident_id: UUID
    acquired_at: datetime
    renewed_at: datetime
    expires_at: datetime
    released_at: datetime | None
    released_by: str | None
    reconciliation_required: bool
    created_at: datetime
    updated_at: datetime


class InternalResourceLockResponse(ResourceLockResponse):
    fencing_token: int


class InternalResourceLockAcquireResponse(ApiModel):
    lock: InternalResourceLockResponse
    duplicate: bool
