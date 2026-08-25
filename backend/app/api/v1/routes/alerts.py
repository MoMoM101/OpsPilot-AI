import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.core.errors import ApplicationError
from app.core.logging import get_logger
from app.domain.alerts import AlertStatus
from app.schemas.alerts import AlertIngestionResponse, AlertmanagerWebhook, AlertResponse
from app.services.alerts import AlertIngestionService
from app.storage.repositories import AlertRepository

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
logger = get_logger(__name__)


def _verify_webhook_token(configured: str | None, provided: str | None) -> None:
    if configured is None:
        return
    if provided is None or not secrets.compare_digest(configured, provided):
        raise ApplicationError(
            "INVALID_WEBHOOK_TOKEN",
            "Webhook authentication failed",
            status.HTTP_401_UNAUTHORIZED,
        )


@router.post(
    "/alerts/webhook/alertmanager",
    response_model=AlertIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_alertmanager_webhook(
    body: AlertmanagerWebhook,
    request: Request,
    session: Session,
    webhook_token: Annotated[
        str | None,
        Header(alias="X-OpsPilot-Webhook-Token"),
    ] = None,
) -> AlertIngestionResponse:
    settings = request.app.state.settings
    _verify_webhook_token(settings.alertmanager_webhook_token, webhook_token)
    service = AlertIngestionService(session, settings.alert_correlation_window_seconds)
    try:
        result = await service.ingest(body)
    except IntegrityError:
        await session.rollback()
        logger.warning("alert_ingestion_conflict_retry", source="alertmanager")
        result = await service.ingest(body)
    return AlertIngestionResponse.model_validate(result)


@router.get("/alerts", response_model=list[AlertResponse], responses=PAGINATION_RESPONSE)
async def list_alerts(
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    alert_status: Annotated[AlertStatus | None, Query(alias="status")] = None,
    resource_id: UUID | None = None,
    incident_id: UUID | None = None,
) -> list[AlertResponse]:
    repository = AlertRepository(session)
    records = await repository.list(
        limit,
        offset,
        alert_status,
        resource_id,
        incident_id,
    )
    total = await repository.count(alert_status, resource_id, incident_id)
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [AlertResponse.model_validate(record) for record in records]
