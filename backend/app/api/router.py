from fastapi import APIRouter

from app.api.internal.v1.router import router as internal_v1_router
from app.api.runner.v1.router import router as runner_v1_router
from app.api.v1.router import router as v1_router

api_router = APIRouter()
api_router.include_router(v1_router, prefix="/api/v1")
api_router.include_router(runner_v1_router, prefix="/runner/v1", include_in_schema=False)
api_router.include_router(internal_v1_router, prefix="/internal/v1", include_in_schema=False)
