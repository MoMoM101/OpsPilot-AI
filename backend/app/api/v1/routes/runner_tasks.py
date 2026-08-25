from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.core.errors import ApplicationError
from app.domain.runner_tasks import RunnerTaskStatus
from app.schemas.runner_tasks import (
    RunnerTaskCreate,
    RunnerTaskResponse,
)
from app.services.runner_tasks import RunnerTaskService
from app.storage.models import RunnerTaskRecord

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _service(request: Request, session: AsyncSession) -> RunnerTaskService:
    settings = request.app.state.settings
    return RunnerTaskService(
        session,
        runner_lease_seconds=settings.runner_lease_seconds,
        task_lease_seconds=settings.runner_task_lease_seconds,
        max_output_bytes=settings.runner_task_max_output_bytes,
        runner_token_rotation_seconds=settings.runner_token_rotation_seconds,
        runner_token_ttl_seconds=settings.runner_token_ttl_seconds,
        runner_token_grace_seconds=settings.runner_token_grace_seconds,
    )


def _response(record: RunnerTaskRecord) -> RunnerTaskResponse:
    return RunnerTaskResponse.model_validate(record)


@router.post(
    "/runner-tasks",
    response_model=RunnerTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_runner_task(
    body: RunnerTaskCreate,
    request: Request,
    session: Session,
) -> RunnerTaskResponse:
    try:
        task = await _service(request, session).create(
            incident_id=body.incident_id,
            plan_step_id=body.plan_step_id,
            resource_id=body.resource_id,
            runner_id=body.runner_id,
            connector=body.connector,
            operation=body.operation,
            parameters=body.parameters,
            idempotency_key=body.idempotency_key,
            timeout_seconds=body.timeout_seconds,
            max_attempts=body.max_attempts,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise ApplicationError(
            "TASK_IDEMPOTENCY_CONFLICT",
            "Task idempotency key already exists",
            409,
        ) from exc
    return _response(task)


@router.get(
    "/runner-tasks", response_model=list[RunnerTaskResponse], responses=PAGINATION_RESPONSE
)
async def list_runner_tasks(
    request: Request,
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    task_status: Annotated[RunnerTaskStatus | None, Query(alias="status")] = None,
    incident_id: UUID | None = None,
    runner_id: UUID | None = None,
    plan_step_id: UUID | None = None,
) -> list[RunnerTaskResponse]:
    records, total = await _service(request, session).list(
        limit,
        offset,
        task_status,
        incident_id,
        runner_id,
        plan_step_id,
    )
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [_response(record) for record in records]
