import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from app.core.logging import get_logger

RecoveryScan = Callable[[], Awaitable[dict[str, int]]]
ControlPlaneMode = Literal["recovering", "normal", "read_only"]
logger = get_logger(__name__)


class ControlPlaneModeService:
    def __init__(self, *, recovery_enabled: bool) -> None:
        self.mode: ControlPlaneMode = "recovering" if recovery_enabled else "normal"
        self.reason_code: str | None = None
        self.recovery_enabled = recovery_enabled
        self.attempts = 0
        self.last_attempt_at: datetime | None = None
        self.last_recovered_at: datetime | None = None
        self.last_result: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def recover(self, scan: RecoveryScan) -> bool:
        if not self.recovery_enabled:
            return True
        async with self._lock:
            self.mode = "recovering"
            self.reason_code = "STARTUP_RECOVERY_IN_PROGRESS"
            self.attempts += 1
            self.last_attempt_at = datetime.now(UTC)
            try:
                self.last_result = await scan()
            except Exception as exc:
                self.mode = "read_only"
                self.reason_code = "STARTUP_RECOVERY_FAILED"
                logger.error(
                    "control_plane_recovery_failed",
                    attempt=self.attempts,
                    error_type=type(exc).__name__,
                )
                return False
            self.mode = "normal"
            self.reason_code = None
            self.last_recovered_at = datetime.now(UTC)
            logger.info("control_plane_recovery_completed", **self.last_result)
            return True

    async def probe(self) -> bool:
        return self.mode == "normal"

    def writable(self) -> bool:
        return self.mode == "normal"

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "reasonCode": self.reason_code,
            "recoveryEnabled": self.recovery_enabled,
            "recoveryAttempts": self.attempts,
            "lastRecoveryAttemptAt": self.last_attempt_at,
            "lastRecoveredAt": self.last_recovered_at,
            "lastRecoveryResult": self.last_result,
        }
