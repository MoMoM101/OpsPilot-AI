from fastapi import APIRouter

from app.schemas.action_capabilities import ActionCapabilityCatalogResponse
from app.services.action_capabilities import action_capability_catalog

router = APIRouter()


@router.get("/action-capabilities", response_model=ActionCapabilityCatalogResponse)
async def get_action_capability_catalog() -> ActionCapabilityCatalogResponse:
    return action_capability_catalog()
