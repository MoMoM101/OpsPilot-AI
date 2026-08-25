from fastapi import APIRouter

from app.api.runner.v1.routes import router as service_router

router = APIRouter()
router.include_router(service_router, tags=["runner-service"])
