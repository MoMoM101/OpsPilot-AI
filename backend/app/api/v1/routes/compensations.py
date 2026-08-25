from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.core.errors import ApplicationError
from app.schemas.compensations import (
    CompensationCreate,
    CompensationDecision,
    CompensationDispatch,
    CompensationEscalate,
    CompensationExecutionResponse,
    CompensationResponse,
)
from app.services.compensations import CompensationService
from app.storage.repositories import CompensationExecutionRepository, CompensationRepository

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _service(request: Request, session: AsyncSession) -> CompensationService:
    settings = request.app.state.settings
    return CompensationService(
        session,
        execution_lease_seconds=settings.action_execution_lease_seconds,
        resource_lock_lease_seconds=settings.resource_lock_lease_seconds,
        runner_lease_seconds=settings.runner_lease_seconds,
        runner_token_rotation_seconds=settings.runner_token_rotation_seconds,
        runner_token_ttl_seconds=settings.runner_token_ttl_seconds,
        runner_token_grace_seconds=settings.runner_token_grace_seconds,
    )


@router.post(
    "/actions/{action_id}/compensation",
    response_model=CompensationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_compensation(
    action_id: UUID, body: CompensationCreate, request: Request, session: Session
) -> CompensationResponse:
    record, _ = await _service(request, session).create(
        action_id,
        parameters=dict(body.parameters),
        idempotency_key=body.idempotency_key,
        expires_in_seconds=body.expires_in_seconds,
    )
    return CompensationResponse.model_validate(record)


@router.get(
    "/compensations", response_model=list[CompensationResponse], responses=PAGINATION_RESPONSE
)
async def list_compensations(
    session: Session,
    response: Response,
    incident_id: Annotated[UUID | None, Query(alias="incidentId")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CompensationResponse]:
    repository = CompensationRepository(session)
    records = await repository.list(
        incident_id=incident_id, limit=limit, offset=offset
    )
    total = await repository.count(incident_id=incident_id)
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [CompensationResponse.model_validate(record) for record in records]


@router.post("/compensations/{compensation_id}/decision", response_model=CompensationResponse)
async def decide_compensation(
    compensation_id: UUID,
    body: CompensationDecision,
    request: Request,
    session: Session,
) -> CompensationResponse:
    record = await _service(request, session).decide(
        compensation_id,
        approve=body.decision == "approve",
        expected_version=body.expected_version,
        comment=body.comment,
    )
    return CompensationResponse.model_validate(record)


@router.post(
    "/compensations/{compensation_id}/dispatch",
    response_model=CompensationExecutionResponse,
)
async def dispatch_compensation(
    compensation_id: UUID,
    body: CompensationDispatch,
    request: Request,
    session: Session,
) -> CompensationExecutionResponse:
    execution = await _service(request, session).dispatch(
        compensation_id,
        expected_version=body.expected_version,
    )
    return CompensationExecutionResponse.model_validate(execution)


@router.get(
    "/compensations/{compensation_id}/execution",
    response_model=CompensationExecutionResponse,
)
async def get_compensation_execution(
    compensation_id: UUID, request: Request, session: Session
) -> CompensationExecutionResponse:
    compensation = await CompensationRepository(session).get(compensation_id)
    if compensation is None:
        raise ApplicationError("COMPENSATION_NOT_FOUND", "Compensation does not exist", 404)
    execution = await CompensationExecutionRepository(session).get_for_request(compensation_id)
    if execution is None:
        raise ApplicationError("COMPENSATION_EXECUTION_NOT_FOUND", "Execution does not exist", 404)
    return CompensationExecutionResponse.model_validate(execution)


@router.post("/compensations/{compensation_id}/escalate", response_model=CompensationResponse)
async def escalate_compensation(
    compensation_id: UUID,
    body: CompensationEscalate,
    request: Request,
    session: Session,
) -> CompensationResponse:
    record = await _service(request, session).escalate(
        compensation_id, expected_version=body.expected_version, reason=body.reason
    )
    return CompensationResponse.model_validate(record)
