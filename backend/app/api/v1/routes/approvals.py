from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.domain.approvals import ApprovalStatus
from app.schemas.approvals import (
    ApprovalCreate,
    ApprovalDecisionRequest,
    ApprovalResponse,
)
from app.services.approvals import ApprovalService
from app.storage.models import ApprovalRecord

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _response(record: ApprovalRecord) -> ApprovalResponse:
    response = ApprovalResponse.model_validate(record)
    expires_at = response.expires_at
    normalized = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
    if response.status == ApprovalStatus.PENDING and normalized <= datetime.now(UTC):
        return response.model_copy(update={"status": ApprovalStatus.EXPIRED})
    return response


@router.post("/approvals", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_approval(body: ApprovalCreate, session: Session) -> ApprovalResponse:
    record = await ApprovalService(session).create(
        policy_decision_id=body.policy_decision_id,
        parameters=body.parameters,
        editable_parameter_keys=body.editable_parameter_keys,
        expires_in_seconds=body.expires_in_seconds,
    )
    return _response(record)


@router.get("/approvals", response_model=list[ApprovalResponse], responses=PAGINATION_RESPONSE)
async def list_approvals(
    session: Session,
    response: Response,
    incident_id: Annotated[UUID | None, Query(alias="incidentId")] = None,
    approval_status: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ApprovalResponse]:
    records = await ApprovalService(session).list(
        incident_id=incident_id,
        status=approval_status,
        limit=limit,
        offset=offset,
    )
    total = await ApprovalService(session).count(
        incident_id=incident_id,
        status=approval_status,
    )
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    responses = [_response(record) for record in records]
    return responses


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    session: Session,
) -> ApprovalResponse:
    record = await ApprovalService(session).decide(
        approval_id,
        decision=body.decision,
        expected_version=body.expected_version,
        comment=body.comment,
        parameter_edits=body.parameter_edits,
    )
    return _response(record)
