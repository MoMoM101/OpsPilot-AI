from fastapi import APIRouter

from app.api.internal.v1.routes.resource_locks import router as resource_locks_router
from app.api.internal.v1.routes.runtime import router as runtime_router

router = APIRouter()
router.include_router(runtime_router, tags=["internal-runtime"])
router.include_router(resource_locks_router, tags=["internal-resource-locks"])
