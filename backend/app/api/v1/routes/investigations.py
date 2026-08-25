from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.core.errors import ApplicationError
from app.domain.investigations import (
    InvestigationGraphDefinition,
    InvestigationRunStatus,
    get_investigation_graph,
    list_investigation_graphs,
)
from app.schemas.investigations import (
    InvestigationCheckpointResponse,
    InvestigationGraphNodeResponse,
    InvestigationGraphResponse,
    InvestigationHITLWaitResponse,
    InvestigationRunCancel,
    InvestigationRunCreate,
    InvestigationRunResponse,
)
from app.services.investigation_hitl import InvestigationHITLService
from app.services.investigations import InvestigationService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _graph_response(
    definition: InvestigationGraphDefinition,
) -> InvestigationGraphResponse:
    return InvestigationGraphResponse(
        version=definition.version,
        entry_node=definition.entry_node,
        nodes=[
            InvestigationGraphNodeResponse(
                key=node.key,
                phase=node.phase,
                side_effecting=node.side_effecting,
                description=node.description,
            )
            for node in definition.nodes
        ],
    )


@router.get("/investigation-graphs", response_model=list[InvestigationGraphResponse])
async def list_graph_definitions() -> list[InvestigationGraphResponse]:
    return [_graph_response(graph) for graph in list_investigation_graphs()]


@router.get(
    "/investigation-graphs/{graph_version}",
    response_model=InvestigationGraphResponse,
)
async def get_graph_definition(graph_version: str) -> InvestigationGraphResponse:
    graph = get_investigation_graph(graph_version)
    if graph is None:
        raise ApplicationError(
            "INVESTIGATION_GRAPH_VERSION_UNAVAILABLE",
            f"Investigation graph version '{graph_version}' is not available",
            404,
        )
    return _graph_response(graph)


@router.post(
    "/incidents/{incident_id}/investigation-runs",
    response_model=InvestigationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_investigation_run(
    incident_id: UUID,
    body: InvestigationRunCreate,
    session: Session,
) -> InvestigationRunResponse:
    run = await InvestigationService(session).create_run(
        incident_id=incident_id,
        idempotency_key=body.idempotency_key,
        graph_version=body.graph_version,
        max_iterations=body.max_iterations,
        max_model_requests=body.max_model_requests,
    )
    return InvestigationRunResponse.model_validate(run)


@router.get(
    "/incidents/{incident_id}/investigation-runs",
    response_model=list[InvestigationRunResponse],
    responses=PAGINATION_RESPONSE,
)
async def list_investigation_runs(
    incident_id: UUID,
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[InvestigationRunResponse]:
    runs, total = await InvestigationService(session).list_runs(
        incident_id, limit, offset
    )
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [InvestigationRunResponse.model_validate(run) for run in runs]


@router.get(
    "/investigation-runs/{run_id}",
    response_model=InvestigationRunResponse,
)
async def get_investigation_run(
    run_id: UUID,
    session: Session,
) -> InvestigationRunResponse:
    run = await InvestigationService(session).get_run(run_id)
    return InvestigationRunResponse.model_validate(run)


@router.post(
    "/investigation-runs/{run_id}/cancel",
    response_model=InvestigationRunResponse,
)
async def cancel_investigation_run(
    run_id: UUID,
    body: InvestigationRunCancel,
    session: Session,
) -> InvestigationRunResponse:
    run = await InvestigationService(session).transition_run(
        run_id=run_id,
        expected_version=body.expected_version,
        target=InvestigationRunStatus.CANCELLED,
        error_code=None,
    )
    return InvestigationRunResponse.model_validate(run)


@router.get(
    "/investigation-runs/{run_id}/checkpoints",
    response_model=list[InvestigationCheckpointResponse],
)
async def list_investigation_checkpoints(
    run_id: UUID,
    session: Session,
    after_sequence: Annotated[int, Query(alias="after_sequence", ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[InvestigationCheckpointResponse]:
    checkpoints = await InvestigationService(session).list_checkpoints(
        run_id,
        after_sequence,
        limit,
    )
    return [
        InvestigationCheckpointResponse.model_validate(checkpoint) for checkpoint in checkpoints
    ]


@router.get(
    "/investigation-runs/{run_id}/hitl-waits",
    response_model=list[InvestigationHITLWaitResponse],
    responses=PAGINATION_RESPONSE,
)
async def list_investigation_hitl_waits(
    run_id: UUID,
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[InvestigationHITLWaitResponse]:
    waits, total = await InvestigationHITLService(session).list_waits(
        run_id, limit, offset
    )
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [InvestigationHITLWaitResponse.model_validate(wait) for wait in waits]
