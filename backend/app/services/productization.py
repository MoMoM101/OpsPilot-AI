from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.runners import RunnerStatus
from app.schemas.system import (
    DeploymentPreflightCheckResponse,
    DeploymentPreflightResponse,
    SetupStatusResponse,
)
from app.storage.models import EnvironmentRecord, RunnerRecord
from app.storage.repositories import PrincipalRepository


class ProductizationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.principals = PrincipalRepository(session)

    async def setup_status(self) -> SetupStatusResponse:
        initial_admin_created = await self._initial_admin_created()
        authentication_enabled = self.settings.control_plane_auth_enabled
        initialization_required = authentication_enabled and not initial_admin_created
        return SetupStatusResponse(
            status="initialization_required" if initialization_required else "ready",
            service=self.settings.app_name,
            version=self.settings.app_version,
            authentication_enabled=authentication_enabled,
            initial_admin_created=initial_admin_created,
            bootstrap_available=(
                initialization_required
                and self.settings.control_plane_bootstrap_token is not None
            ),
        )

    async def preflight(
        self,
        *,
        readiness_checks: dict[str, bool],
        control_plane_mode: str,
    ) -> DeploymentPreflightResponse:
        now = datetime.now(UTC)
        initial_admin_created = await self._initial_admin_created()
        environment_count = int(
            await self.session.scalar(select(func.count()).select_from(EnvironmentRecord)) or 0
        )
        online_runner_count = int(
            await self.session.scalar(
                select(func.count()).select_from(RunnerRecord).where(
                    RunnerRecord.status == RunnerStatus.ONLINE,
                    RunnerRecord.lease_expires_at > now,
                )
            )
            or 0
        )
        checks = [
            self._check(
                "database",
                readiness_checks.get("database", True),
                True,
                "Database is reachable and ready",
                "Database readiness check is failing",
            ),
            self._check(
                "control_plane_mode",
                control_plane_mode == "normal",
                True,
                "Control Plane is operating normally",
                f"Control Plane is in {control_plane_mode} mode",
            ),
            self._check(
                "initial_admin",
                not self.settings.control_plane_auth_enabled or initial_admin_created,
                True,
                "Initial Admin setup is complete",
                "Create the first unrestricted user Admin",
            ),
            self._check(
                "environment",
                environment_count > 0,
                True,
                f"{environment_count} Environment(s) configured",
                "Create at least one Environment",
            ),
            self._check(
                "runner",
                online_runner_count > 0,
                False,
                f"{online_runner_count} online Runner(s) available",
                "No online Runner is available; observations and Actions cannot run",
            ),
            self._check(
                "agent_runtime",
                self.settings.agent_runtime_enabled,
                False,
                "Agent runtime is enabled",
                "Agent runtime is disabled; automated investigations will not run",
            ),
            self._check(
                "alert_ingestion",
                self.settings.alertmanager_webhook_token is not None,
                False,
                "Alertmanager webhook authentication is configured",
                "Alertmanager webhook token is not configured",
            ),
        ]
        return DeploymentPreflightResponse(
            status=(
                "action_required"
                if any(check.blocking and check.status != "pass" for check in checks)
                else "ready"
            ),
            checked_at=now,
            checks=checks,
        )

    async def _initial_admin_created(self) -> bool:
        setup = await self.principals.get_initial_admin_setup()
        if setup is not None and setup.completed_at is not None:
            return True
        return await self.principals.has_active_admin()

    @staticmethod
    def _check(
        key: str,
        passed: bool,
        blocking: bool,
        success_message: str,
        failure_message: str,
    ) -> DeploymentPreflightCheckResponse:
        return DeploymentPreflightCheckResponse(
            key=key,
            status="pass" if passed else "action_required" if blocking else "warning",
            blocking=blocking,
            message=success_message if passed else failure_message,
        )
