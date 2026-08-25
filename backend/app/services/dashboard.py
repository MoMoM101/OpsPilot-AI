from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.actions import ActionRequestStatus
from app.domain.approvals import ApprovalStatus
from app.domain.incidents import IncidentStatus
from app.storage.repositories import (
    ActionRequestRepository,
    ApprovalRepository,
    IncidentListItem,
    IncidentRepository,
    ResourceLockRepository,
    RunnerRepository,
)

_ACTIVE_STATUSES = set(IncidentStatus) - {
    IncidentStatus.RESOLVED,
    IncidentStatus.CLOSED,
    IncidentStatus.FAILED,
    IncidentStatus.CANCELLED,
}
_WAITING_HUMAN_STATUSES = {
    IncidentStatus.WAITING_APPROVAL,
    IncidentStatus.NEEDS_HUMAN,
}
_TERMINAL_EVALUATED_STATUSES = {
    IncidentStatus.RESOLVED,
    IncidentStatus.CLOSED,
    IncidentStatus.FAILED,
}


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    active_tasks: int
    waiting_human: int
    root_cause_rate: int
    mean_investigation_seconds: int
    runner_online: int
    runner_total: int
    pending_approvals: int
    active_resource_locks: int
    unknown_actions: int
    actions_requiring_attention: int
    observability_lost_incidents: int
    incidents: list[IncidentListItem]


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.incidents = IncidentRepository(session)
        self.approvals = ApprovalRepository(session)
        self.actions = ActionRequestRepository(session)
        self.resource_locks = ResourceLockRepository(session)
        self.runners = RunnerRepository(session)

    async def snapshot(self) -> DashboardSnapshot:
        now = datetime.now(UTC)
        active_tasks = await self.incidents.count_by_statuses(_ACTIVE_STATUSES)
        waiting_human = await self.incidents.count_by_statuses(_WAITING_HUMAN_STATUSES)
        terminal_count = await self.incidents.count_by_statuses(_TERMINAL_EVALUATED_STATUSES)
        resolved_count = await self.incidents.count_by_statuses(
            {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}
        )
        root_cause_rate = round(resolved_count / terminal_count * 100) if terminal_count else 0
        completed = await self.incidents.list_completed()
        mean_seconds = (
            round(
                sum((item.updated_at - item.created_at).total_seconds() for item in completed)
                / len(completed)
            )
            if completed
            else 0
        )
        latest = await self.incidents.list(3, 0, None, None)
        runner_total, runner_online = await self.runners.dashboard_counts(now)
        pending_approvals = await self.approvals.count(
            incident_id=None,
            status=ApprovalStatus.PENDING,
        )
        active_resource_locks = await self.resource_locks.count_active(now)
        unknown_actions = await self.actions.count_by_statuses({ActionRequestStatus.UNKNOWN})
        actions_requiring_attention = await self.actions.count_by_statuses(
            {
                ActionRequestStatus.UNKNOWN,
                ActionRequestStatus.FAILED,
                ActionRequestStatus.VERIFICATION_FAILED,
                ActionRequestStatus.ESCALATED,
            }
        )
        observability_lost_incidents = await self.incidents.count_by_statuses(
            {IncidentStatus.OBSERVABILITY_LOST}
        )
        return DashboardSnapshot(
            active_tasks=active_tasks,
            waiting_human=waiting_human,
            root_cause_rate=root_cause_rate,
            mean_investigation_seconds=mean_seconds,
            runner_online=runner_online,
            runner_total=runner_total,
            pending_approvals=pending_approvals,
            active_resource_locks=active_resource_locks,
            unknown_actions=unknown_actions,
            actions_requiring_attention=actions_requiring_attention,
            observability_lost_incidents=observability_lost_incidents,
            incidents=latest,
        )
