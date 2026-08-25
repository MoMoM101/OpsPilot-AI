from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.api.v1.routes.plans import to_plan_response
from app.core.errors import ApplicationError
from app.core.principal_context import principal_context
from app.domain.incidents import IncidentStatus, Severity
from app.schemas.hypotheses import HypothesisSummary
from app.schemas.incidents import (
    IncidentCreate,
    IncidentDetailResponse,
    IncidentEventResponse,
    IncidentResponse,
    IncidentTransitionRequest,
)
from app.schemas.plans import ToolBudgetResponse
from app.services.incidents import IncidentService
from app.storage.models import IncidentEventRecord
from app.storage.repositories import IncidentListItem, IncidentRepository, PlanRepository

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
INCIDENT_DETAIL_TIMELINE_LIMIT = 100


def _to_response(item: IncidentListItem) -> IncidentResponse:
    incident = item.incident
    return IncidentResponse(
        id=incident.id,
        title=incident.title,
        status=incident.status,
        severity=incident.severity,
        resource=item.resource_name,
        environment=item.environment_name,
        resource_id=incident.resource_id,
        owner=incident.owner,
        version=incident.version,
        observability_status=(
            "lost" if incident.status == IncidentStatus.OBSERVABILITY_LOST else "observable"
        ),
        observability_runner_id=incident.observability_runner_id,
        observability_lost_at=incident.observability_lost_at,
        hypothesis=(
            HypothesisSummary.model_validate(item.hypothesis)
            if item.hypothesis is not None
            else None
        ),
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )


async def _detail(repository: IncidentRepository, incident_id: UUID) -> IncidentDetailResponse:
    item = await repository.get_view(incident_id)
    if item is None:
        raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
    incident = _to_response(item)
    events = await repository.list_events(
        incident_id, limit=INCIDENT_DETAIL_TIMELINE_LIMIT
    )
    timeline_total = await repository.count_events(incident_id)
    plan_repository = PlanRepository(repository.session)
    plan = await plan_repository.get_latest(incident_id)
    plan_response = await to_plan_response(plan_repository, plan) if plan else None
    return IncidentDetailResponse(
        **incident.model_dump(),
        trace_id=item.incident.trace_id,
        event_cursor=item.incident.event_cursor,
        autonomy_level=cast(
            Literal["L0", "L1", "L2", "L3"],
            item.incident.autonomy_level,
        ),
        plan_version=plan_response.version if plan_response else 0,
        replan_count=item.incident.replan_count,
        tool_budget=ToolBudgetResponse(
            used=item.incident.tool_budget_used,
            limit=item.incident.tool_budget_limit,
        ),
        steps=plan_response.steps if plan_response else [],
        timeline=[
            _to_event_response(event)
            for event in events
        ],
        timeline_total=timeline_total,
        timeline_truncated=timeline_total > len(events),
    )


def _to_event_response(event: IncidentEventRecord) -> IncidentEventResponse:
    return IncidentEventResponse(
        id=event.id,
        type=event.event_type,
        occurred_at=event.occurred_at,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        payload=event.payload,
    )


@router.post("/incidents", response_model=IncidentDetailResponse, status_code=201)
async def create_incident(body: IncidentCreate, session: Session) -> IncidentDetailResponse:
    incident_id = await IncidentService(session).create(
        body.title,
        body.severity,
        body.resource_id,
        body.owner,
    )
    return await _detail(IncidentRepository(session), incident_id)


@router.get(
    "/incidents", response_model=list[IncidentResponse], responses=PAGINATION_RESPONSE
)
async def list_incidents(
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    incident_status: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    severity: Severity | None = None,
    environment_id: Annotated[UUID | None, Query(alias="environmentId")] = None,
    query: Annotated[str | None, Query(alias="q", min_length=1, max_length=200)] = None,
) -> list[IncidentResponse]:
    repository = IncidentRepository(session)
    items = await repository.list(
        limit,
        offset,
        incident_status,
        severity,
        environment_id,
        query,
    )
    total = await repository.count(
        incident_status,
        severity,
        environment_id,
        query,
    )
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [_to_response(item) for item in items]


@router.get("/incidents/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(incident_id: UUID, session: Session) -> IncidentDetailResponse:
    return await _detail(IncidentRepository(session), incident_id)


@router.get(
    "/incidents/{incident_id}/timeline",
    response_model=list[IncidentEventResponse],
    responses=PAGINATION_RESPONSE,
)
async def get_incident_timeline(
    incident_id: UUID,
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[IncidentEventResponse]:
    repository = IncidentRepository(session)
    if await repository.get(incident_id) is None:
        raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
    events = await repository.list_events(incident_id, limit=limit, offset=offset)
    total = await repository.count_events(incident_id)
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [_to_event_response(event) for event in events]


@router.post(
    "/incidents/{incident_id}/transitions",
    response_model=IncidentDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def transition_incident_status(
    incident_id: UUID,
    body: IncidentTransitionRequest,
    session: Session,
) -> IncidentDetailResponse:
    principal = principal_context.get()
    await IncidentService(session).transition(
        incident_id,
        body.target,
        body.expected_version,
        principal.actor_id if principal else body.actor_id,
    )
    return await _detail(IncidentRepository(session), incident_id)
