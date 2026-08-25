from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.schemas.demo import (
    DemoCleanupRequest,
    DemoCleanupResponse,
    DemoInitializeResponse,
    DemoStatusResponse,
)
from app.services.demo import DemoDataService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/demo/status", response_model=DemoStatusResponse)
async def demo_status(request: Request, session: Session) -> DemoStatusResponse:
    return await DemoDataService(session, request.app.state.settings).status()


@router.post("/demo/initialize", response_model=DemoInitializeResponse)
async def initialize_demo(request: Request, session: Session) -> DemoInitializeResponse:
    return await DemoDataService(session, request.app.state.settings).initialize()


@router.post("/demo/cleanup", response_model=DemoCleanupResponse)
async def cleanup_demo(
    body: DemoCleanupRequest,
    request: Request,
    session: Session,
) -> DemoCleanupResponse:
    return await DemoDataService(session, request.app.state.settings).cleanup(
        body.expected_generation
    )
