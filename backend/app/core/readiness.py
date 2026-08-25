from collections.abc import Awaitable, Callable
from time import perf_counter

from app.core.logging import get_logger

Probe = Callable[[], Awaitable[bool]]
logger = get_logger(__name__)


class ReadinessService:
    def __init__(self) -> None:
        self._probes: dict[str, Probe] = {}

    def register(self, name: str, probe: Probe) -> None:
        self._probes[name] = probe

    async def check(self) -> dict[str, object]:
        checks: dict[str, bool] = {}
        for name, probe in self._probes.items():
            started_at = perf_counter()
            try:
                checks[name] = await probe()
            except Exception as exc:
                checks[name] = False
                logger.warning(
                    "readiness_probe_failed",
                    probe=name,
                    error_type=type(exc).__name__,
                    duration_ms=round((perf_counter() - started_at) * 1000, 2),
                )
        is_ready = all(checks.values())
        return {"status": "ready" if is_ready else "not_ready", "checks": checks}
