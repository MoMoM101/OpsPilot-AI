from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.domain.runners import RunnerStatus
from app.schemas.runners import RunnerResponse
from app.services.runners import RunnerService
from app.storage.models import RunnerRecord

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _capabilities(record: RunnerRecord) -> list[dict[str, Any]]:
    connectors = record.capabilities.get("connectors", [])
    return connectors if isinstance(connectors, list) else []


def _runner_response(record: RunnerRecord) -> RunnerResponse:
    return RunnerResponse(
        id=record.id,
        name=record.name,
        status=record.status,
        software_version=record.software_version,
        environment_id=record.environment_id,
        capabilities=_capabilities(record),
        labels=record.labels,
        token_expires_at=record.token_expires_at,
        last_seen_at=record.last_seen_at,
        lease_expires_at=record.lease_expires_at,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/runners", response_model=list[RunnerResponse], responses=PAGINATION_RESPONSE)
async def list_runners(
    request: Request,
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    runner_status: Annotated[RunnerStatus | None, Query(alias="status")] = None,
) -> list[RunnerResponse]:
    settings = request.app.state.settings
    records, total = await RunnerService(
        session,
        settings.runner_lease_seconds,
        token_rotation_seconds=settings.runner_token_rotation_seconds,
        token_ttl_seconds=settings.runner_token_ttl_seconds,
        token_grace_seconds=settings.runner_token_grace_seconds,
    ).list_runners(limit, offset, runner_status)
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [_runner_response(record) for record in records]
