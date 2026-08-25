import asyncio
import json
from collections.abc import AsyncIterator
from time import monotonic
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.core.errors import ApplicationError
from app.schemas.events import AgentEvent
from app.storage.models import OutboxEventRecord
from app.storage.repositories import IncidentRepository, OutboxRepository

router = APIRouter()


def _parse_last_event_id(value: str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        sequence = int(value)
    except ValueError as exc:
        raise ApplicationError("INVALID_LAST_EVENT_ID", "Last-Event-ID must be an integer") from exc
    if sequence < 0:
        raise ApplicationError("INVALID_LAST_EVENT_ID", "Last-Event-ID cannot be negative")
    return sequence


def _to_agent_event(record: OutboxEventRecord) -> AgentEvent:
    return AgentEvent(
        id=record.event_id,
        sequence=record.sequence,
        type=record.event_type,
        incident_id=record.incident_id,
        trace_id=record.trace_id,
        version=record.aggregate_version,
        occurred_at=record.occurred_at,
        payload=record.payload,
    )


def format_sse_event(record: OutboxEventRecord) -> str:
    event = _to_agent_event(record)
    data = json.dumps(event.model_dump(mode="json", by_alias=True), ensure_ascii=False)
    return f"id: {record.sequence}\nevent: {record.event_type}\ndata: {data}\n\n"


async def _event_stream(
    request: Request,
    incident_id: UUID,
    cursor: int,
    follow: bool,
) -> AsyncIterator[str]:
    database = request.app.state.database
    settings = request.app.state.settings
    last_heartbeat = monotonic()

    while True:
        if await request.is_disconnected():
            return
        async with database.session_factory() as session:
            events = await OutboxRepository(session).list_after(
                incident_id,
                cursor,
                settings.sse_batch_size,
            )
        if events:
            for event in events:
                cursor = event.sequence
                yield format_sse_event(event)
            last_heartbeat = monotonic()
            if not follow:
                return
            continue
        if not follow:
            return
        if monotonic() - last_heartbeat >= settings.sse_heartbeat_seconds:
            yield ": heartbeat\n\n"
            last_heartbeat = monotonic()
        await asyncio.sleep(settings.sse_poll_interval_seconds)


@router.get("/incidents/{incident_id}/stream", response_class=StreamingResponse)
async def stream_incident_events(
    incident_id: UUID,
    request: Request,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    follow: Annotated[bool, Query()] = True,
) -> StreamingResponse:
    async with request.app.state.database.session_factory() as session:
        if await IncidentRepository(session).get(incident_id) is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
    cursor = _parse_last_event_id(last_event_id)
    return StreamingResponse(
        _event_stream(request, incident_id, cursor, follow),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
