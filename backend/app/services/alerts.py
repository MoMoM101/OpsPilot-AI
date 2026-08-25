import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.alerts import AlertStatus
from app.domain.incidents import Severity
from app.schemas.alerts import AlertmanagerAlert, AlertmanagerWebhook
from app.services.events import EventRecorder
from app.services.incidents import IncidentService
from app.storage.models import AlertRecord, IncidentRecord, ResourceRecord
from app.storage.repositories import (
    AlertRepository,
    IncidentRepository,
    ResourceRepository,
)
from app.storage.transactions import commit_session

_SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "warn": Severity.MEDIUM,
    "medium": Severity.MEDIUM,
    "info": Severity.LOW,
    "low": Severity.LOW,
}
_RESOURCE_LABELS = ("instance", "resource", "service", "job")
_SENSITIVE_KEY_PARTS = ("authorization", "cookie", "password", "secret", "token")


@dataclass(frozen=True, slots=True)
class AlertIngestionResult:
    received: int = 0
    created: int = 0
    deduplicated: int = 0
    incidents_created: int = 0
    incidents_correlated: int = 0
    unmatched: int = 0


class AlertIngestionService:
    def __init__(self, session: AsyncSession, correlation_window_seconds: int) -> None:
        self.session = session
        self.correlation_window = timedelta(seconds=correlation_window_seconds)
        self.alerts = AlertRepository(session)
        self.incidents = IncidentRepository(session)
        self.resources = ResourceRepository(session)
        self.events = EventRecorder(session)

    async def ingest(self, webhook: AlertmanagerWebhook) -> AlertIngestionResult:
        counters = {
            "received": len(webhook.alerts),
            "created": 0,
            "deduplicated": 0,
            "incidents_created": 0,
            "incidents_correlated": 0,
            "unmatched": 0,
        }
        received_at = datetime.now(UTC)
        for incoming in webhook.alerts:
            resource = await self._resolve_resource(incoming.labels)
            alert, is_new, status_changed = await self._upsert_alert(
                incoming,
                resource,
                received_at,
            )
            counters["created" if is_new else "deduplicated"] += 1
            if alert.status == AlertStatus.FIRING and alert.incident_id is None:
                incident, incident_created = await self._correlate_firing_alert(
                    alert,
                    resource,
                    received_at,
                )
                if incident is None:
                    counters["unmatched"] += 1
                elif incident_created:
                    counters["incidents_created"] += 1
                else:
                    counters["incidents_correlated"] += 1
            elif status_changed and alert.status == AlertStatus.RESOLVED:
                await self._record_resolution(alert, received_at)

        await commit_session(self.session)
        return AlertIngestionResult(**counters)

    async def _resolve_resource(self, labels: dict[str, str]) -> ResourceRecord | None:
        raw_resource_id = labels.get("resource_id")
        if raw_resource_id:
            try:
                resource_id = UUID(raw_resource_id)
            except ValueError:
                resource_id = None
            if resource_id:
                resource = await self.resources.get(resource_id)
                if resource:
                    return resource
        names = list(dict.fromkeys(labels[key] for key in _RESOURCE_LABELS if labels.get(key)))
        return await self.resources.find_unique_by_names(names)

    async def _upsert_alert(
        self,
        incoming: AlertmanagerAlert,
        resource: ResourceRecord | None,
        received_at: datetime,
    ) -> tuple[AlertRecord, bool, bool]:
        fingerprint = incoming.fingerprint or self._hash(incoming.labels)
        dedup_key = self._hash(
            {"fingerprint": fingerprint, "starts_at": incoming.starts_at.isoformat()}
        )
        payload_hash = self._hash(incoming.model_dump(mode="json", by_alias=True))
        existing = await self.alerts.get_by_dedup_key("alertmanager", dedup_key)
        new_status = AlertStatus(incoming.status)
        severity = self._severity(incoming.labels)
        title = self._title(incoming)
        if existing:
            previous_status = existing.status
            existing.status = new_status
            existing.severity = severity
            existing.title = title
            existing.labels = self._redact(incoming.labels)
            existing.annotations = self._redact(incoming.annotations)
            existing.ends_at = incoming.ends_at
            existing.last_seen_at = received_at
            existing.occurrence_count += 1
            existing.generator_url = incoming.generator_url
            existing.raw_payload_hash = payload_hash
            if existing.resource_id is None and resource:
                existing.resource_id = resource.id
            await self.session.flush()
            return existing, False, previous_status != new_status
        record = await self.alerts.create(
            source="alertmanager",
            dedup_key=dedup_key,
            fingerprint=fingerprint,
            status=new_status,
            severity=severity,
            title=title,
            labels=self._redact(incoming.labels),
            annotations=self._redact(incoming.annotations),
            starts_at=incoming.starts_at,
            ends_at=incoming.ends_at,
            received_at=received_at,
            generator_url=incoming.generator_url,
            raw_payload_hash=payload_hash,
            resource_id=resource.id if resource else None,
        )
        return record, True, False

    async def _correlate_firing_alert(
        self,
        alert: AlertRecord,
        resource: ResourceRecord | None,
        occurred_at: datetime,
    ) -> tuple[IncidentRecord | None, bool]:
        if resource is None:
            return None, False
        incident = await self.incidents.find_active_for_resource(
            resource.id,
            occurred_at - self.correlation_window,
        )
        created = incident is None
        if incident is None:
            incident_id = await IncidentService(self.session).create(
                alert.title,
                alert.severity,
                resource.id,
                None,
                commit=False,
            )
            incident = await self.incidents.get(incident_id)
            if incident is None:
                raise RuntimeError("Created incident could not be loaded")
        else:
            incident.version += 1
            incident.updated_at = occurred_at
        alert.incident_id = incident.id
        await self.events.record(
            incident,
            "incident.correlated",
            occurred_at,
            "system",
            {
                "alert_id": str(alert.id),
                "fingerprint": alert.fingerprint,
                "occurrence_count": alert.occurrence_count,
            },
            aggregate_type="alert",
            aggregate_id=alert.id,
            aggregate_version=alert.occurrence_count,
        )
        return incident, created

    async def _record_resolution(self, alert: AlertRecord, occurred_at: datetime) -> None:
        if alert.incident_id is None:
            return
        incident = await self.incidents.get(alert.incident_id)
        if incident is None:
            return
        await self.events.record(
            incident,
            "alert.resolved",
            occurred_at,
            "system",
            {"alert_id": str(alert.id), "fingerprint": alert.fingerprint},
            aggregate_type="alert",
            aggregate_id=alert.id,
            aggregate_version=alert.occurrence_count,
        )

    @staticmethod
    def _severity(labels: dict[str, str]) -> Severity:
        raw = labels.get("severity", "medium").lower()
        return _SEVERITY_MAP.get(raw, Severity.MEDIUM)

    @staticmethod
    def _title(alert: AlertmanagerAlert) -> str:
        title = (
            alert.annotations.get("summary")
            or alert.annotations.get("description")
            or alert.labels.get("alertname")
            or "Alertmanager incident"
        )
        return title[:300]

    @staticmethod
    def _hash(value: object) -> str:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _redact(values: dict[str, str]) -> dict[str, str]:
        return {
            key: "[REDACTED]"
            if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS)
            else value
            for key, value in values.items()
        }
