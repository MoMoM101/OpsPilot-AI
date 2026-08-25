from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.alerts import AlertStatus
from app.domain.incidents import Severity
from app.schemas.base import ApiModel, to_camel


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    status: str = Field(pattern=r"^(firing|resolved)$")
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime
    ends_at: datetime | None = None
    generator_url: str | None = None
    fingerprint: str | None = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Alert timestamps must include a timezone")
        return value


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    version: str | None = None
    group_key: str | None = None
    status: str | None = None
    receiver: str | None = None
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=1000)


class AlertIngestionResponse(ApiModel):
    received: int
    created: int
    deduplicated: int
    incidents_created: int
    incidents_correlated: int
    unmatched: int


class AlertResponse(ApiModel):
    id: UUID
    source: str
    fingerprint: str
    status: AlertStatus
    severity: Severity
    title: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: datetime
    ends_at: datetime | None
    received_at: datetime
    last_seen_at: datetime
    occurrence_count: int
    generator_url: str | None
    resource_id: UUID | None
    incident_id: UUID | None
