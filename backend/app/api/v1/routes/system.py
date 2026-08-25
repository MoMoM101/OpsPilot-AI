from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.schemas.system import (
    ControlPlaneModeResponse,
    DeploymentPreflightResponse,
    HealthResponse,
    ModelConnectionCheckResponse,
    ReadinessResponse,
    SetupStatusResponse,
    WorkerHealthResponse,
)
from app.services.productization import ProductizationService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/health", response_model=HealthResponse, summary="Process liveness")
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@router.get(
    "/setup/status",
    response_model=SetupStatusResponse,
    summary="Public first-run setup status",
)
async def setup_status(request: Request, session: Session) -> SetupStatusResponse:
    return await ProductizationService(session, request.app.state.settings).setup_status()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    summary="Service readiness",
)
async def ready(request: Request) -> ReadinessResponse | JSONResponse:
    readiness = await request.app.state.readiness.check()
    response = ReadinessResponse(**readiness)
    if response.status == "not_ready":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(mode="json"),
        )
    return response


@router.get(
    "/worker-health",
    response_model=WorkerHealthResponse,
    include_in_schema=False,
    summary="Background worker health",
)
async def worker_health(request: Request) -> WorkerHealthResponse:
    workers = request.app.state.worker_health.snapshot()
    degraded = any(item["enabled"] and not item["healthy"] for item in workers.values())
    return WorkerHealthResponse(
        status="degraded" if degraded else "ok",
        workers=workers,
    )


@router.get(
    "/system/mode",
    response_model=ControlPlaneModeResponse,
    summary="Control Plane operating mode",
)
async def control_plane_mode(request: Request) -> ControlPlaneModeResponse:
    return ControlPlaneModeResponse(**request.app.state.control_plane_mode.snapshot())


@router.get(
    "/system/preflight",
    response_model=DeploymentPreflightResponse,
    summary="Deployment productization preflight",
)
async def deployment_preflight(
    request: Request,
    session: Session,
) -> DeploymentPreflightResponse:
    readiness = await request.app.state.readiness.check()
    mode = request.app.state.control_plane_mode.snapshot()["mode"]
    return await ProductizationService(session, request.app.state.settings).preflight(
        readiness_checks=readiness["checks"],
        control_plane_mode=mode,
    )


@router.post(
    "/system/model-connection-check",
    response_model=ModelConnectionCheckResponse,
    summary="Run a bounded model provider connectivity check",
)
async def model_connection_check(request: Request) -> ModelConnectionCheckResponse:
    return cast(
        ModelConnectionCheckResponse,
        await request.app.state.model_diagnostics.check(),
    )


@router.post(
    "/system/recovery",
    response_model=ControlPlaneModeResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ControlPlaneModeResponse}},
    summary="Retry startup recovery",
)
async def retry_startup_recovery(
    request: Request,
) -> ControlPlaneModeResponse | JSONResponse:
    recovered = await request.app.state.control_plane_mode.recover(
        request.app.state.control_plane_recovery.scan
    )
    response = ControlPlaneModeResponse(**request.app.state.control_plane_mode.snapshot())
    if not recovered:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(mode="json", by_alias=True),
            headers={"Retry-After": "30"},
        )
    return response
