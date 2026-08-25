from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.domain.incidents import IncidentStatus
from app.schemas.dashboard import DashboardResponse, DashboardSafetyResponse
from app.schemas.hypotheses import HypothesisSummary
from app.schemas.incidents import IncidentResponse
from app.services.dashboard import DashboardService
from app.storage.repositories import IncidentListItem

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _incident_response(item: IncidentListItem) -> IncidentResponse:
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


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(session: Session) -> DashboardResponse:
    snapshot = await DashboardService(session).snapshot()
    return DashboardResponse(
        active_tasks=snapshot.active_tasks,
        waiting_human=snapshot.waiting_human,
        root_cause_rate=snapshot.root_cause_rate,
        mean_investigation_seconds=snapshot.mean_investigation_seconds,
        runner_online=snapshot.runner_online,
        runner_total=snapshot.runner_total,
        safety=DashboardSafetyResponse(
            pending_approvals=snapshot.pending_approvals,
            active_resource_locks=snapshot.active_resource_locks,
            unknown_actions=snapshot.unknown_actions,
            actions_requiring_attention=snapshot.actions_requiring_attention,
            observability_lost_incidents=snapshot.observability_lost_incidents,
        ),
        incidents=[_incident_response(item) for item in snapshot.incidents],
    )
