from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.schemas.resource_locks import (
    InternalResourceLockAcquireResponse,
    InternalResourceLockResponse,
    ResourceLockTokenRequest,
)
from app.services.resource_locks import ResourceLockService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _service(request: Request, session: AsyncSession) -> ResourceLockService:
    return ResourceLockService(session, request.app.state.settings.resource_lock_lease_seconds)


@router.post(
    "/actions/{action_id}/lock",
    response_model=InternalResourceLockAcquireResponse,
    status_code=status.HTTP_201_CREATED,
)
async def acquire_resource_lock(
    action_id: UUID, request: Request, session: Session
) -> InternalResourceLockAcquireResponse:
    lock, duplicate = await _service(request, session).acquire(action_id)
    return InternalResourceLockAcquireResponse(
        lock=InternalResourceLockResponse.model_validate(lock), duplicate=duplicate
    )


@router.post("/actions/{action_id}/lock/renew", response_model=InternalResourceLockResponse)
async def renew_resource_lock(
    action_id: UUID,
    body: ResourceLockTokenRequest,
    request: Request,
    session: Session,
) -> InternalResourceLockResponse:
    lock = await _service(request, session).renew(action_id, body.fencing_token)
    return InternalResourceLockResponse.model_validate(lock)


@router.post("/actions/{action_id}/lock/release", response_model=InternalResourceLockResponse)
async def release_resource_lock(
    action_id: UUID,
    body: ResourceLockTokenRequest,
    request: Request,
    session: Session,
) -> InternalResourceLockResponse:
    lock = await _service(request, session).release(action_id, body.fencing_token)
    return InternalResourceLockResponse.model_validate(lock)
