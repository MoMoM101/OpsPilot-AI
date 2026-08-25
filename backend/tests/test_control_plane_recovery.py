import asyncio

from app.core.control_plane_mode import ControlPlaneModeService


def test_recovery_failure_enters_read_only_without_exposing_exception() -> None:
    async def scenario() -> None:
        mode = ControlPlaneModeService(recovery_enabled=True)

        async def fail() -> dict[str, int]:
            raise RuntimeError("database password must not leak")

        assert await mode.recover(fail) is False
        snapshot = mode.snapshot()
        assert snapshot["mode"] == "read_only"
        assert snapshot["reasonCode"] == "STARTUP_RECOVERY_FAILED"
        assert snapshot["recoveryAttempts"] == 1
        assert "password" not in str(snapshot)

    asyncio.run(scenario())


def test_recovery_retry_restores_normal_mode_and_records_counts() -> None:
    async def scenario() -> None:
        mode = ControlPlaneModeService(recovery_enabled=True)

        async def succeed() -> dict[str, int]:
            return {
                "staleRunners": 1,
                "unknownActions": 2,
                "unknownCompensations": 3,
            }

        assert await mode.recover(succeed) is True
        snapshot = mode.snapshot()
        assert snapshot["mode"] == "normal"
        assert snapshot["reasonCode"] is None
        assert snapshot["lastRecoveredAt"] is not None
        assert snapshot["lastRecoveryResult"] == {
            "staleRunners": 1,
            "unknownActions": 2,
            "unknownCompensations": 3,
        }

    asyncio.run(scenario())
