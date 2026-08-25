from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.core.errors import ApplicationError
from app.domain.actions import ActionRequestStatus
from app.schemas.action_executions import ActionExecutionResponse, ActionReconcileRequest
from app.schemas.action_verifications import ActionVerificationResponse
from app.schemas.actions import (
    ActionRequestCancel,
    ActionRequestCreate,
    ActionRequestCreateResponse,
    ActionRequestResponse,
)
from app.services.action_dispatcher import ActionDispatcherService
from app.services.actions import ActionRequestService
from app.storage.repositories import (
    ActionRequestRepository,
    ActionVerificationRepository,
    RunnerTaskRepository,
)

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _dispatcher(request: Request, session: AsyncSession) -> ActionDispatcherService:
    settings = request.app.state.settings
    return ActionDispatcherService(
        session,
        execution_lease_seconds=settings.action_execution_lease_seconds,
        resource_lock_lease_seconds=settings.resource_lock_lease_seconds,
        runner_lease_seconds=settings.runner_lease_seconds,
        runner_token_rotation_seconds=settings.runner_token_rotation_seconds,
        runner_token_ttl_seconds=settings.runner_token_ttl_seconds,
        runner_token_grace_seconds=settings.runner_token_grace_seconds,
    )


@router.post(
    "/actions",
    response_model=ActionRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_action(body: ActionRequestCreate, session: Session) -> ActionRequestCreateResponse:
    record, replayed = await ActionRequestService(session).create(
        policy_decision_id=body.policy_decision_id,
        approval_id=body.approval_id,
        parameters=body.parameters,
        verification_criteria=body.verification_criteria,
        rollback_capability=body.rollback_capability,
        idempotency_key=body.idempotency_key,
    )
    return ActionRequestCreateResponse(
        action=ActionRequestResponse.model_validate(record), replayed=replayed
    )


@router.get("/actions", response_model=list[ActionRequestResponse], responses=PAGINATION_RESPONSE)
async def list_actions(
    session: Session,
    response: Response,
    incident_id: Annotated[UUID | None, Query(alias="incidentId")] = None,
    action_status: Annotated[ActionRequestStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ActionRequestResponse]:
    repository = ActionRequestRepository(session)
    records = await repository.list(
        incident_id=incident_id,
        status=action_status,
        limit=limit,
        offset=offset,
    )
    total = await repository.count(incident_id=incident_id, status=action_status)
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [ActionRequestResponse.model_validate(record) for record in records]


@router.post("/actions/{action_id}/cancel", response_model=ActionRequestResponse)
async def cancel_action(
    action_id: UUID, body: ActionRequestCancel, session: Session
) -> ActionRequestResponse:
    record = await ActionRequestService(session).cancel(
        action_id, expected_version=body.expected_version, reason=body.reason
    )
    return ActionRequestResponse.model_validate(record)


@router.post("/actions/{action_id}/dispatch", response_model=ActionExecutionResponse)
async def dispatch_action(
    action_id: UUID,
    request: Request,
    session: Session,
) -> ActionExecutionResponse:
    execution = await _dispatcher(request, session).dispatch(action_id)
    return ActionExecutionResponse.model_validate(execution)


@router.get("/actions/{action_id}/execution", response_model=ActionExecutionResponse)
async def get_action_execution(
    action_id: UUID, request: Request, session: Session
) -> ActionExecutionResponse:
    dispatcher = _dispatcher(request, session)
    action = await ActionRequestRepository(session).get(action_id)
    if action is None:
        raise ApplicationError("ACTION_NOT_FOUND", "Action Request does not exist", 404)
    execution = await dispatcher.executions.get_for_action(action_id)
    if execution is None:
        raise ApplicationError("ACTION_EXECUTION_NOT_FOUND", "Action Execution does not exist", 404)
    return ActionExecutionResponse.model_validate(execution)


@router.get(
    "/actions/{action_id}/verification",
    response_model=ActionVerificationResponse,
)
async def get_action_verification(action_id: UUID, session: Session) -> ActionVerificationResponse:
    verification = await ActionVerificationRepository(session).get_for_action(action_id)
    if verification is None:
        raise ApplicationError(
            "ACTION_VERIFICATION_NOT_FOUND", "Action Verification does not exist", 404
        )
    task = await RunnerTaskRepository(session).get_for_verification(verification.id)
    return ActionVerificationResponse.model_validate(verification).model_copy(
        update={"runner_task_id": task.id if task else None}
    )


@router.post("/actions/{action_id}/reconcile", response_model=ActionExecutionResponse)
async def reconcile_action(
    action_id: UUID,
    body: ActionReconcileRequest,
    request: Request,
    session: Session,
) -> ActionExecutionResponse:
    execution = await _dispatcher(request, session).reconcile(
        action_id,
        expected_version=body.expected_version,
        succeeded=body.outcome == "succeeded",
        summary=body.summary,
        error_code=body.error_code,
    )
    return ActionExecutionResponse.model_validate(execution)
