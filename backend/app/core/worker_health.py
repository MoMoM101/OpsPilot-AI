import asyncio
import contextlib
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class _WorkerState:
    name: str
    enabled: bool
    stale_after_seconds: float
    error_threshold: int
    started_at: datetime | None = None
    started_monotonic: float | None = None
    last_heartbeat_at: datetime | None = None
    last_heartbeat_monotonic: float | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    consecutive_errors: int = 0
    total_errors: int = 0
    last_error_type: str | None = None
    task: asyncio.Task[None] | None = None


class WorkerHealthRegistry:
    def __init__(self, *, stale_multiplier: float = 3, error_threshold: int = 3) -> None:
        self.stale_multiplier = stale_multiplier
        self.error_threshold = error_threshold
        self._workers: dict[str, _WorkerState] = {}

    def register(self, name: str, *, enabled: bool, interval_seconds: float) -> None:
        self._workers[name] = _WorkerState(
            name=name,
            enabled=enabled,
            stale_after_seconds=max(5.0, interval_seconds * self.stale_multiplier),
            error_threshold=self.error_threshold,
        )

    def start(self, name: str, task: asyncio.Task[None]) -> None:
        state = self._workers[name]
        now = datetime.now(UTC)
        state.started_at = now
        state.started_monotonic = monotonic()
        state.task = task

    def heartbeat(self, name: str) -> None:
        state = self._workers[name]
        state.last_heartbeat_at = datetime.now(UTC)
        state.last_heartbeat_monotonic = monotonic()

    def success(self, name: str) -> None:
        state = self._workers[name]
        self.heartbeat(name)
        state.last_success_at = datetime.now(UTC)
        state.consecutive_errors = 0
        state.last_error_type = None

    def failure(self, name: str, exc: Exception) -> None:
        state = self._workers[name]
        self.heartbeat(name)
        state.last_error_at = datetime.now(UTC)
        state.consecutive_errors += 1
        state.total_errors += 1
        state.last_error_type = type(exc).__name__

    async def probe(self, name: str) -> bool:
        return self._healthy(self._workers[name])

    def snapshot(self) -> dict[str, dict[str, object]]:
        return {
            name: {
                "enabled": state.enabled,
                "healthy": self._healthy(state),
                "taskRunning": state.task is not None and not state.task.done(),
                "startedAt": state.started_at,
                "lastHeartbeatAt": state.last_heartbeat_at,
                "lastSuccessAt": state.last_success_at,
                "lastErrorAt": state.last_error_at,
                "consecutiveErrors": state.consecutive_errors,
                "totalErrors": state.total_errors,
                "lastErrorType": state.last_error_type,
                "staleAfterSeconds": state.stale_after_seconds,
            }
            for name, state in self._workers.items()
        }

    async def run_monitored(self, name: str, operation: Awaitable[T]) -> T:
        """Run one worker iteration while emitting heartbeats during slow I/O/model calls."""
        state = self._workers[name]
        task = asyncio.ensure_future(operation)
        heartbeat_interval = max(0.5, state.stale_after_seconds / 3)
        try:
            while not task.done():
                self.heartbeat(name)
                done, _ = await asyncio.wait({task}, timeout=heartbeat_interval)
                if done:
                    break
            return await task
        except asyncio.CancelledError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise

    @staticmethod
    def _healthy(state: _WorkerState) -> bool:
        if not state.enabled:
            return True
        if state.task is None or state.task.done():
            return False
        if state.consecutive_errors >= state.error_threshold:
            return False
        now = monotonic()
        reference = state.last_heartbeat_monotonic or state.started_monotonic
        return reference is not None and now - reference <= state.stale_after_seconds
