import secrets
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.errors import ApplicationError
from app.schemas.action_executions import (
    RunnerActionClaimRequest,
    RunnerActionClaimResponse,
    RunnerActionCompleteRequest,
    RunnerActionCompleteResponse,
    RunnerActionExecution,
    RunnerActionExecutionResponse,
    RunnerActionLeaseRequest,
)
from app.schemas.compensations import RunnerCompensationExecutionResponse
from app.schemas.runner_tasks import (
    RunnerTaskClaimRequest,
    RunnerTaskClaimResponse,
    RunnerTaskCompleteRequest,
    RunnerTaskCompleteResponse,
    RunnerTaskExecution,
    RunnerTaskRenewRequest,
    RunnerTaskResponse,
)
from app.schemas.runners import (
    RunnerHeartbeatRequest,
    RunnerHeartbeatResponse,
    RunnerRegisterRequest,
    RunnerRegistrationResponse,
    RunnerResponse,
)
from app.services.action_dispatcher import ActionDispatcherService
from app.services.compensations import CompensationService
from app.services.runner_tasks import RunnerTaskService
from app.services.runners import RunnerService
from app.storage.models import RunnerRecord, RunnerTaskRecord

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _verify_bootstrap_token(configured: str | None, provided: str | None) -> None:
    if configured is None:
        return
    if provided is None or not secrets.compare_digest(configured, provided):
        raise ApplicationError(
            "INVALID_RUNNER_BOOTSTRAP_TOKEN",
            "Runner bootstrap authentication failed",
            status.HTTP_401_UNAUTHORIZED,
        )


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise ApplicationError("RUNNER_TOKEN_REQUIRED", "Runner token is required", 401)
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise ApplicationError("INVALID_RUNNER_AUTHORIZATION", "Expected a Bearer token", 401)
    return token


def _runner_response(record: RunnerRecord) -> RunnerResponse:
    connectors = record.capabilities.get("connectors", [])
    capabilities: list[dict[str, Any]] = connectors if isinstance(connectors, list) else []
    return RunnerResponse(
        id=record.id,
        name=record.name,
        status=record.status,
        software_version=record.software_version,
        environment_id=record.environment_id,
        capabilities=capabilities,
        labels=record.labels,
        token_expires_at=record.token_expires_at,
        last_seen_at=record.last_seen_at,
        lease_expires_at=record.lease_expires_at,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _task_service(request: Request, session: AsyncSession) -> RunnerTaskService:
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


def _action_service(request: Request, session: AsyncSession) -> ActionDispatcherService:
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


def _compensation_service(request: Request, session: AsyncSession) -> CompensationService:
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


def _runner_service(request: Request, session: AsyncSession) -> RunnerService:
    settings = request.app.state.settings
    return RunnerService(
        session,
        settings.runner_lease_seconds,
        token_rotation_seconds=settings.runner_token_rotation_seconds,
        token_ttl_seconds=settings.runner_token_ttl_seconds,
        token_grace_seconds=settings.runner_token_grace_seconds,
    )


def _task_response(record: RunnerTaskRecord) -> RunnerTaskResponse:
    return RunnerTaskResponse.model_validate(record)


@router.post(
    "/runners/register",
    response_model=RunnerRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_runner(
    body: RunnerRegisterRequest,
    request: Request,
    session: Session,
    bootstrap_token: Annotated[
        str | None,
        Header(alias="X-OpsPilot-Runner-Bootstrap-Token"),
    ] = None,
) -> RunnerRegistrationResponse:
    settings = request.app.state.settings
    _verify_bootstrap_token(settings.runner_bootstrap_token, bootstrap_token)
    try:
        registration = await _runner_service(request, session).register(
            name=body.name,
            software_version=body.software_version,
            environment_id=body.environment_id,
            capabilities=[
                item.model_dump(mode="json", by_alias=True) for item in body.capabilities
            ],
            labels=body.labels,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise ApplicationError("RUNNER_NAME_CONFLICT", "Runner name already exists", 409) from exc
    runner = _runner_response(registration.runner)
    return RunnerRegistrationResponse(
        **runner.model_dump(),
        access_token=registration.access_token,
        fencing_token=registration.fencing_token,
    )


@router.post("/runners/{runner_id}/heartbeat", response_model=RunnerHeartbeatResponse)
async def heartbeat_runner(
    runner_id: UUID,
    body: RunnerHeartbeatRequest,
    request: Request,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerHeartbeatResponse:
    result = await _runner_service(request, session).heartbeat(
        runner_id=runner_id,
        access_token=_bearer_token(authorization),
        heartbeat_id=body.heartbeat_id,
        software_version=body.software_version,
        capabilities=(
            [item.model_dump(mode="json", by_alias=True) for item in body.capabilities]
            if body.capabilities is not None
            else None
        ),
        labels=body.labels,
    )
    return RunnerHeartbeatResponse(
        runner_id=result.runner.id,
        status=result.runner.status,
        lease_expires_at=result.runner.lease_expires_at,
        fencing_token=result.fencing_token,
        version=result.runner.version,
        duplicate=result.duplicate,
        access_token=result.access_token,
        token_expires_at=result.runner.token_expires_at,
    )


@router.post("/runners/{runner_id}/tasks/claim", response_model=RunnerTaskClaimResponse)
async def claim_runner_task(
    runner_id: UUID,
    body: RunnerTaskClaimRequest,
    request: Request,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerTaskClaimResponse:
    task = await _task_service(request, session).claim(
        runner_id=runner_id,
        access_token=_bearer_token(authorization),
        runner_fencing_token=body.runner_fencing_token,
    )
    if task is None:
        return RunnerTaskClaimResponse(task=None)
    if task.task_fencing_token is None or task.lease_expires_at is None:
        raise ApplicationError("INVALID_TASK_LEASE", "Task lease is incomplete", 500)
    return RunnerTaskClaimResponse(
        task=RunnerTaskExecution(
            id=task.id,
            incident_id=task.incident_id,
            plan_step_id=task.plan_step_id,
            resource_id=task.resource_id,
            connector=task.connector,
            operation=task.operation,
            parameters=task.parameters,
            timeout_seconds=task.timeout_seconds,
            attempt=task.attempt,
            task_fencing_token=task.task_fencing_token,
            lease_expires_at=task.lease_expires_at,
        )
    )


@router.post(
    "/runners/{runner_id}/tasks/{task_id}/renew",
    response_model=RunnerTaskResponse,
)
async def renew_runner_task(
    runner_id: UUID,
    task_id: UUID,
    body: RunnerTaskRenewRequest,
    request: Request,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerTaskResponse:
    task = await _task_service(request, session).renew(
        runner_id=runner_id,
        task_id=task_id,
        access_token=_bearer_token(authorization),
        task_fencing_token=body.task_fencing_token,
    )
    return _task_response(task)


@router.post(
    "/runners/{runner_id}/tasks/{task_id}/complete",
    response_model=RunnerTaskCompleteResponse,
)
async def complete_runner_task(
    runner_id: UUID,
    task_id: UUID,
    body: RunnerTaskCompleteRequest,
    request: Request,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerTaskCompleteResponse:
    task, duplicate = await _task_service(request, session).complete(
        runner_id=runner_id,
        task_id=task_id,
        access_token=_bearer_token(authorization),
        completion_id=body.completion_id,
        task_fencing_token=body.task_fencing_token,
        succeeded=body.status == "succeeded",
        summary=body.summary,
        output=body.output,
        redacted=body.redacted,
        output_truncated=body.output_truncated,
        error_code=body.error_code,
    )
    return RunnerTaskCompleteResponse(task=_task_response(task), duplicate=duplicate)


@router.post("/runners/{runner_id}/actions/claim", response_model=RunnerActionClaimResponse)
async def claim_runner_action(
    runner_id: UUID,
    body: RunnerActionClaimRequest,
    request: Request,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerActionClaimResponse:
    access_token = _bearer_token(authorization)
    claimed = await _action_service(request, session).claim(
        runner_id=runner_id,
        access_token=access_token,
        runner_fencing_token=body.runner_fencing_token,
    )
    if claimed is None:
        compensation = await _compensation_service(request, session).claim(
            runner_id=runner_id,
            access_token=access_token,
            runner_fencing_token=body.runner_fencing_token,
        )
        if compensation is None:
            return RunnerActionClaimResponse(execution=None)
        compensation_execution, compensation_request = compensation
        if compensation_execution.lease_expires_at is None:
            raise ApplicationError("INVALID_ACTION_LEASE", "Action lease is incomplete", 500)
        return RunnerActionClaimResponse(
            execution=RunnerActionExecution(
                execution_kind="compensation",
                execution_id=compensation_execution.id,
                action_id=compensation_request.action_request_id,
                compensation_id=compensation_request.id,
                incident_id=compensation_request.incident_id,
                resource_id=compensation_request.resource_id,
                capability=compensation_request.capability,
                parameters=compensation_request.parameters,
                verification_criteria=[],
                rollback_capability=None,
                execution_fencing_token=compensation_execution.execution_fencing_token,
                resource_fencing_token=compensation_execution.resource_fencing_token,
                lease_expires_at=compensation_execution.lease_expires_at,
            )
        )
    execution, action = claimed
    if execution.lease_expires_at is None:
        raise ApplicationError("INVALID_ACTION_LEASE", "Action lease is incomplete", 500)
    return RunnerActionClaimResponse(
        execution=RunnerActionExecution(
            execution_id=execution.id,
            action_id=action.id,
            incident_id=action.incident_id,
            resource_id=action.resource_id,
            capability=action.capability,
            parameters=action.parameters,
            verification_criteria=action.verification_criteria,
            rollback_capability=action.rollback_capability,
            execution_fencing_token=execution.execution_fencing_token,
            resource_fencing_token=execution.resource_fencing_token,
            lease_expires_at=execution.lease_expires_at,
        )
    )


@router.post(
    "/runners/{runner_id}/actions/{execution_id}/renew",
    response_model=RunnerActionExecutionResponse | RunnerCompensationExecutionResponse,
)
async def renew_runner_action(
    runner_id: UUID,
    execution_id: UUID,
    body: RunnerActionLeaseRequest,
    request: Request,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerActionExecutionResponse | RunnerCompensationExecutionResponse:
    access_token = _bearer_token(authorization)
    try:
        execution = await _action_service(request, session).renew(
            runner_id=runner_id,
            execution_id=execution_id,
            access_token=access_token,
            execution_fencing_token=body.execution_fencing_token,
            resource_fencing_token=body.resource_fencing_token,
        )
        return RunnerActionExecutionResponse.model_validate(execution)
    except ApplicationError as exc:
        if exc.code != "ACTION_EXECUTION_NOT_FOUND":
            raise
    compensation = await _compensation_service(request, session).renew(
        runner_id=runner_id,
        execution_id=execution_id,
        access_token=access_token,
        execution_fencing_token=body.execution_fencing_token,
        resource_fencing_token=body.resource_fencing_token,
    )
    return RunnerCompensationExecutionResponse.model_validate(compensation)


@router.post(
    "/runners/{runner_id}/actions/{execution_id}/complete",
    response_model=RunnerActionCompleteResponse,
)
async def complete_runner_action(
    runner_id: UUID,
    execution_id: UUID,
    body: RunnerActionCompleteRequest,
    request: Request,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerActionCompleteResponse:
    access_token = _bearer_token(authorization)
    try:
        execution, duplicate = await _action_service(request, session).complete(
            runner_id=runner_id,
            execution_id=execution_id,
            access_token=access_token,
            completion_id=body.completion_id,
            execution_fencing_token=body.execution_fencing_token,
            resource_fencing_token=body.resource_fencing_token,
            succeeded=body.status == "succeeded",
            summary=body.summary,
            error_code=body.error_code,
        )
        response: RunnerActionExecutionResponse | RunnerCompensationExecutionResponse = (
            RunnerActionExecutionResponse.model_validate(execution)
        )
    except ApplicationError as exc:
        if exc.code != "ACTION_EXECUTION_NOT_FOUND":
            raise
        compensation, duplicate = await _compensation_service(request, session).complete(
            runner_id=runner_id,
            execution_id=execution_id,
            access_token=access_token,
            completion_id=body.completion_id,
            execution_fencing_token=body.execution_fencing_token,
            resource_fencing_token=body.resource_fencing_token,
            succeeded=body.status == "succeeded",
            summary=body.summary,
            error_code=body.error_code,
        )
        response = RunnerCompensationExecutionResponse.model_validate(compensation)
    return RunnerActionCompleteResponse(execution=response, duplicate=duplicate)
