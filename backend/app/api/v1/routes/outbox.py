from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.core.errors import ApplicationError
from app.schemas.outbox import (
    OutboxDeadLetterResponse,
    OutboxReplayResponse,
    OutboxStatusResponse,
)
from app.storage.repositories import OutboxRepository
from app.storage.transactions import commit_session

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/outbox/status", response_model=OutboxStatusResponse)
async def outbox_status(session: Session) -> OutboxStatusResponse:
    pending, dead_letters, oldest = await OutboxRepository(session).delivery_stats()
    now = datetime.now(UTC)
    normalized_oldest = (
        oldest if oldest is None or oldest.tzinfo is not None else oldest.replace(tzinfo=UTC)
    )
    return OutboxStatusResponse(
        pending_count=pending,
        dead_letter_count=dead_letters,
        oldest_pending_at=normalized_oldest,
        oldest_pending_age_seconds=(
            max(0.0, (now - normalized_oldest).total_seconds())
            if normalized_oldest is not None
            else None
        ),
    )


@router.get(
    "/outbox/dead-letters",
    response_model=list[OutboxDeadLetterResponse],
    responses=PAGINATION_RESPONSE,
)
async def list_outbox_dead_letters(
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OutboxDeadLetterResponse]:
    repository = OutboxRepository(session)
    records = await repository.list_dead_letters(limit, offset)
    total = await repository.count_dead_letters()
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [OutboxDeadLetterResponse.model_validate(record) for record in records]


@router.post(
    "/outbox/dead-letters/{event_id}/replay",
    response_model=OutboxReplayResponse,
)
async def replay_outbox_dead_letter(
    event_id: UUID,
    session: Session,
) -> OutboxReplayResponse:
    repository = OutboxRepository(session)
    record = await repository.get_by_event_id(event_id, for_update=True)
    if record is None:
        raise ApplicationError("OUTBOX_EVENT_NOT_FOUND", "Outbox event does not exist", 404)
    if record.dead_lettered_at is None:
        raise ApplicationError(
            "OUTBOX_EVENT_NOT_DEAD_LETTERED",
            "Only Dead Letter events can be replayed",
            409,
        )
    now = datetime.now(UTC)
    record.dead_lettered_at = None
    record.publish_attempts = 0
    record.next_attempt_at = now
    record.last_error = None
    record.last_status_code = None
    await commit_session(session)
    return OutboxReplayResponse(
        event_id=record.event_id,
        status="pending",
        next_attempt_at=now,
    )
