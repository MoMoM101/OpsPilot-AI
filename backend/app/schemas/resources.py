from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import ApiModel


class EnvironmentCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    description: str | None = Field(default=None, max_length=2000)


class EnvironmentResponse(ApiModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ResourceCreate(ApiModel):
    environment_id: UUID
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=50)
    criticality: str = Field(default="medium", pattern=r"^(critical|high|medium|low)$")
    attributes: dict[str, Any] = Field(default_factory=dict)


class ResourceResponse(ApiModel):
    id: UUID
    environment_id: UUID
    name: str
    kind: str
    criticality: str
    version: int
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime
