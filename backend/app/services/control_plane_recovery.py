import asyncio

from app.core.config import Settings
from app.core.control_plane_mode import ControlPlaneModeService
from app.services.action_dispatcher import ActionDispatcherService
from app.services.compensations import CompensationService
from app.services.observability import ObservabilityService
from app.storage.database import Database


class ControlPlaneRecoveryService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    async def scan(self) -> dict[str, int]:
        async with self.database.session_factory() as session:
            common = {
                "execution_lease_seconds": self.settings.action_execution_lease_seconds,
                "resource_lock_lease_seconds": self.settings.resource_lock_lease_seconds,
                "runner_lease_seconds": self.settings.runner_lease_seconds,
                "runner_token_rotation_seconds": self.settings.runner_token_rotation_seconds,
                "runner_token_ttl_seconds": self.settings.runner_token_ttl_seconds,
                "runner_token_grace_seconds": self.settings.runner_token_grace_seconds,
            }
            stale_runners = await ObservabilityService(session).expire_stale_runners()
            actions = await ActionDispatcherService(session, **common).recover_expired()
            compensations = await CompensationService(session, **common).recover_expired()
            return {
                "staleRunners": stale_runners,
                "unknownActions": actions,
                "unknownCompensations": compensations,
            }


async def retry_recovery_until_ready(
    mode: ControlPlaneModeService,
    recovery: ControlPlaneRecoveryService,
    interval_seconds: float,
) -> None:
    while not mode.writable():
        await asyncio.sleep(interval_seconds)
        if mode.writable():
            return
        await mode.recover(recovery.scan)
