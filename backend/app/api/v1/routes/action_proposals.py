from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.domain.actions import ActionProposalStatus
from app.schemas.action_proposals import ActionProposalResponse
from app.services.action_proposals import ActionProposalService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "/action-proposals",
    response_model=list[ActionProposalResponse],
    responses=PAGINATION_RESPONSE,
)
async def list_action_proposals(
    session: Session,
    response: Response,
    incident_id: Annotated[UUID | None, Query(alias="incident_id")] = None,
    proposal_status: Annotated[ActionProposalStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ActionProposalResponse]:
    service = ActionProposalService(session)
    records = await service.list(incident_id, proposal_status, limit, offset)
    total = await service.count(incident_id, proposal_status)
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [ActionProposalResponse.model_validate(record) for record in records]
