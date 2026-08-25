from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal_context import principal_context
from app.storage.models import IncidentRecord
from app.storage.repositories import IncidentRepository, OutboxRepository


class EventRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self.incident_events = IncidentRepository(session)
        self.outbox = OutboxRepository(session)

    async def record(
        self,
        incident: IncidentRecord,
        event_type: str,
        occurred_at: datetime,
        actor_type: str,
        payload: dict[str, object],
        *,
        aggregate_type: str = "incident",
        aggregate_id: UUID | None = None,
        aggregate_version: int | None = None,
    ) -> None:
        principal = principal_context.get()
        resolved_actor_type = principal.actor_type if principal else actor_type
        actor_id = principal.actor_id if principal else None
        await self.incident_events.add_event(
            incident.id,
            event_type,
            occurred_at,
            resolved_actor_type,
            actor_id,
            payload,
        )
        audited_payload = dict(payload)
        if actor_id is not None:
            audited_payload["actorId"] = actor_id
            audited_payload["actorType"] = resolved_actor_type
        outbox_event = await self.outbox.add(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id or incident.id,
            incident_id=incident.id,
            trace_id=incident.trace_id,
            aggregate_version=aggregate_version or incident.version,
            payload=audited_payload,
            occurred_at=occurred_at,
        )
        incident.event_cursor = await self.incident_events.advance_event_cursor(
            incident.id, outbox_event.sequence
        )
