from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.schemas.connectors import ConnectorCatalogResponse
from app.services.connector_catalog import ConnectorCatalogService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/connectors", response_model=ConnectorCatalogResponse)
async def get_connector_catalog(
    session: Session,
    environment_id: Annotated[UUID | None, Query(alias="environmentId")] = None,
) -> ConnectorCatalogResponse:
    return await ConnectorCatalogService(session).get_catalog(environment_id)
