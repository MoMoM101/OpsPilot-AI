import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.worker_health import WorkerHealthRegistry
from app.domain.incidents import IncidentStatus, transition_incident
from app.domain.runner_tasks import RunnerTaskStatus
from app.domain.runners import RunnerStatus
from app.services.action_verifications import ActionVerificationService
from app.services.events import EventRecorder
from app.storage.database import Database
from app.storage.repositories import (
    IncidentRepository,
    RunnerRepository,
    RunnerTaskRepository,
)
from app.storage.transactions import commit_session

logger = get_logger(__name__)


class ObservabilityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.runners = RunnerRepository(session)
        self.tasks = RunnerTaskRepository(session)
        self.incidents = IncidentRepository(session)
        self.events = EventRecorder(session)

    async def expire_stale_runners(self, now: datetime | None = None) -> int:
        checked_at = now or datetime.now(UTC)
        expired = await self.runners.expired_online(checked_at)
        for runner in expired:
            runner.status = RunnerStatus.OFFLINE
            runner.version += 1
            runner.updated_at = checked_at
            tasks = await self.tasks.leased_for_runner(runner.id)
            incident_tasks: dict[UUID, list[str]] = {}
            for task in tasks:
                incident_tasks.setdefault(task.incident_id, []).append(str(task.id))
                task.lease_expires_at = None
                task.task_fencing_token = None
                task.updated_at = checked_at
                if task.attempt < task.max_attempts:
                    task.status = RunnerTaskStatus.QUEUED
                    task.runner_id = None
                else:
                    task.status = RunnerTaskStatus.FAILED
                    task.error_code = "RUNNER_LEASE_EXPIRED"
                    task.result_summary = "Runner disconnected while task was leased"
                    task.completed_at = checked_at
                    await ActionVerificationService(self.session).finalize_task(
                        task,
                        succeeded=False,
                        now=checked_at,
                    )
            for incident_id, task_ids in incident_tasks.items():
                incident = await self.incidents.get(incident_id, for_update=True)
                if incident is None or incident.status != IncidentStatus.INVESTIGATING:
                    continue
                incident.status = transition_incident(
                    incident.status,
                    IncidentStatus.OBSERVABILITY_LOST,
                )
                incident.observability_runner_id = runner.id
                incident.observability_lost_at = checked_at
                incident.version += 1
                incident.updated_at = checked_at
                await self.events.record(
                    incident,
                    "incident.observability_lost",
                    checked_at,
                    "control_plane",
                    {
                        "runnerId": str(runner.id),
                        "reason": "runner_lease_expired",
                        "taskIds": task_ids,
                        "version": incident.version,
                    },
                )
        if expired:
            await commit_session(self.session)
        return len(expired)

    async def restore_for_runner(self, runner_id: UUID, now: datetime) -> int:
        incidents = await self.incidents.list_observability_lost_for_runner(runner_id)
        for incident in incidents:
            incident.status = transition_incident(
                incident.status,
                IncidentStatus.INVESTIGATING,
            )
            incident.observability_runner_id = None
            incident.observability_lost_at = None
            incident.version += 1
            incident.updated_at = now
            await self.events.record(
                incident,
                "incident.observability_restored",
                now,
                "control_plane",
                {"runnerId": str(runner_id), "version": incident.version},
            )
        return len(incidents)


async def run_observability_monitor(
    database: Database,
    interval_seconds: float,
    health: WorkerHealthRegistry | None = None,
) -> None:
    worker_name = "observability_monitor"
    while True:
        try:

            async def check() -> int:
                async with database.session_factory() as session:
                    return await ObservabilityService(session).expire_stale_runners()

            expired = (
                await health.run_monitored(worker_name, check())
                if health is not None
                else await check()
            )
            if health is not None:
                health.success(worker_name)
            if expired:
                logger.warning("runner_leases_expired", count=expired)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if health is not None:
                health.failure(worker_name, exc)
            logger.error(
                "observability_monitor_failed",
                error_type=type(exc).__name__,
            )
        await asyncio.sleep(interval_seconds)
