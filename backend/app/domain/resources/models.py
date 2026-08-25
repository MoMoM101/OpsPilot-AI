from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Environment:
    id: UUID
    name: str
    slug: str
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Resource:
    id: UUID
    environment_id: UUID
    name: str
    kind: str
    criticality: str
    version: int
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime
