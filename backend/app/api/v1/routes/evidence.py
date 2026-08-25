from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.schemas.evidence import EvidenceResponse
from app.services.evidence import EvidenceService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/evidence/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(evidence_id: UUID, session: Session) -> EvidenceResponse:
    record = await EvidenceService(session).get(evidence_id)
    return EvidenceResponse.model_validate(record)


@router.get(
    "/incidents/{incident_id}/evidence",
    response_model=list[EvidenceResponse],
    responses=PAGINATION_RESPONSE,
)
async def list_incident_evidence(
    incident_id: UUID,
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    evidence_type: Annotated[str | None, Query(max_length=50)] = None,
    resource_id: UUID | None = None,
) -> list[EvidenceResponse]:
    records, total = await EvidenceService(session).list_for_incident(
        incident_id,
        limit,
        offset,
        evidence_type,
        resource_id,
    )
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [EvidenceResponse.model_validate(record) for record in records]
