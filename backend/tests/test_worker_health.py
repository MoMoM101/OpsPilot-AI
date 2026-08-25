import asyncio
import contextlib

from app.core.worker_health import WorkerHealthRegistry


def test_worker_health_degrades_after_repeated_errors_and_recovers() -> None:
    async def scenario() -> None:
        registry = WorkerHealthRegistry(stale_multiplier=2, error_threshold=3)
        registry.register("worker", enabled=True, interval_seconds=1)
        stop = asyncio.Event()
        task = asyncio.create_task(stop.wait())
        registry.start("worker", task)

        assert await registry.probe("worker") is True
        for _ in range(3):
            registry.failure("worker", RuntimeError("temporary failure"))

        degraded = registry.snapshot()["worker"]
        assert degraded["healthy"] is False
        assert degraded["consecutiveErrors"] == 3
        assert degraded["totalErrors"] == 3
        assert degraded["lastErrorType"] == "RuntimeError"

        registry.success("worker")
        recovered = registry.snapshot()["worker"]
        assert recovered["healthy"] is True
        assert recovered["consecutiveErrors"] == 0
        assert recovered["lastSuccessAt"] is not None

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert await registry.probe("worker") is False

    asyncio.run(scenario())


def test_disabled_worker_is_healthy_without_a_task() -> None:
    registry = WorkerHealthRegistry()
    registry.register("optional", enabled=False, interval_seconds=1)

    state = registry.snapshot()["optional"]

    assert state["healthy"] is True
    assert state["taskRunning"] is False
