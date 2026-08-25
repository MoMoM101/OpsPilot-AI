from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.incidents import IncidentStatus, Severity, transition_incident
from app.services.events import EventRecorder
from app.storage.repositories import IncidentRepository, ResourceRepository
from app.storage.transactions import commit_session


class IncidentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.incidents = IncidentRepository(session)
        self.resources = ResourceRepository(session)
        self.events = EventRecorder(session)

    async def create(
        self,
        title: str,
        severity: Severity,
        resource_id: UUID,
        owner: str | None,
        *,
        commit: bool = True,
    ) -> UUID:
        if await self.resources.get(resource_id) is None:
            raise ApplicationError("RESOURCE_NOT_FOUND", "Resource does not exist", 404)
        incident = await self.incidents.create(title, severity, resource_id, owner)
        await self.events.record(
            incident,
            "incident.created",
            datetime.now(UTC),
            "user",
            {"status": incident.status.value},
        )
        if commit:
            await commit_session(self.session)
        return incident.id

    async def transition(
        self,
        incident_id: UUID,
        target: IncidentStatus,
        expected_version: int,
        actor_id: str | None,
    ) -> None:
        incident = await self.incidents.get(incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        if incident.version != expected_version:
            raise ApplicationError(
                "INCIDENT_VERSION_CONFLICT",
                "Incident has changed; reload before retrying",
                409,
            )
        previous = incident.status
        try:
            incident.status = transition_incident(previous, target)
        except ValueError as exc:
            raise ApplicationError("INVALID_INCIDENT_TRANSITION", str(exc), 409) from exc
        incident.version += 1
        incident.updated_at = datetime.now(UTC)
        await self.events.record(
            incident,
            "incident.status_changed",
            incident.updated_at,
            "user",
            {
                "from": previous.value,
                "to": target.value,
                "actor_id": actor_id,
                "version": incident.version,
            },
        )
        await commit_session(self.session)
