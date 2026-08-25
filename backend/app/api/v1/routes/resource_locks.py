from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.schemas.resource_locks import ResourceLockResponse
from app.storage.repositories import ResourceLockRepository

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "/resource-locks", response_model=list[ResourceLockResponse], responses=PAGINATION_RESPONSE
)
async def list_active_resource_locks(
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ResourceLockResponse]:
    repository = ResourceLockRepository(session)
    now = datetime.now(UTC)
    records = await repository.list_active(limit=limit, offset=offset, now=now)
    total = await repository.count_active(now)
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [ResourceLockResponse.model_validate(record) for record in records]
