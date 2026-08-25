from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.schemas.hypotheses import (
    HypothesisCreate,
    HypothesisResponse,
    HypothesisUpdate,
)
from app.services.hypotheses import HypothesisService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/incidents/{incident_id}/hypotheses",
    response_model=HypothesisResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_hypothesis(
    incident_id: UUID,
    body: HypothesisCreate,
    session: Session,
) -> HypothesisResponse:
    record = await HypothesisService(session).create(
        incident_id=incident_id,
        summary=body.summary,
        confidence=body.confidence,
        supporting_evidence_ids=body.supporting_evidence_ids,
        contradicting_evidence_ids=body.contradicting_evidence_ids,
    )
    return HypothesisResponse.model_validate(record)


@router.get(
    "/incidents/{incident_id}/hypotheses",
    response_model=list[HypothesisResponse],
    responses=PAGINATION_RESPONSE,
)
async def list_hypotheses(
    incident_id: UUID,
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[HypothesisResponse]:
    records, total = await HypothesisService(session).list_for_incident(
        incident_id, limit, offset
    )
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [HypothesisResponse.model_validate(record) for record in records]


@router.patch(
    "/incidents/{incident_id}/hypotheses/{hypothesis_id}",
    response_model=HypothesisResponse,
)
async def update_hypothesis(
    incident_id: UUID,
    hypothesis_id: UUID,
    body: HypothesisUpdate,
    session: Session,
) -> HypothesisResponse:
    record = await HypothesisService(session).update(
        incident_id=incident_id,
        hypothesis_id=hypothesis_id,
        expected_version=body.expected_version,
        summary=body.summary,
        confidence=body.confidence,
        status=body.status,
        supporting_evidence_ids=body.supporting_evidence_ids,
        contradicting_evidence_ids=body.contradicting_evidence_ids,
    )
    return HypothesisResponse.model_validate(record)
