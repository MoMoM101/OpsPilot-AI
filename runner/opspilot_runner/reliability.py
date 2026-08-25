import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from opspilot_runner.contracts import ConnectorError


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    state: CircuitState
    consecutive_failures: int
    retry_after_seconds: float


class ConnectorCircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("Circuit breaker failure threshold must be positive")
        if recovery_seconds <= 0:
            raise ValueError("Circuit breaker recovery interval must be positive")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.clock = clock
        self.consecutive_failures = 0
        self.opened_at: float | None = None
        self.probe_in_flight = False

    def before_call(self, connector_name: str) -> bool:
        if self.opened_at is None:
            return False
        elapsed = self.clock() - self.opened_at
        if elapsed < self.recovery_seconds or self.probe_in_flight:
            retry_after = max(0.0, self.recovery_seconds - elapsed)
            raise ConnectorError(
                "CONNECTOR_CIRCUIT_OPEN",
                f"Connector circuit is open: {connector_name}; retry after {retry_after:.1f}s",
            )
        self.probe_in_flight = True
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None
        self.probe_in_flight = False

    def record_failure(self, *, retryable: bool) -> None:
        if not retryable:
            self.probe_in_flight = False
            return
        self.consecutive_failures += 1
        if self.probe_in_flight or self.consecutive_failures >= self.failure_threshold:
            self.opened_at = self.clock()
            self.probe_in_flight = False

    def abandon_call(self) -> None:
        self.probe_in_flight = False

    def snapshot(self) -> CircuitSnapshot:
        if self.opened_at is None:
            state = CircuitState.CLOSED
            retry_after = 0.0
        else:
            elapsed = self.clock() - self.opened_at
            retry_after = max(0.0, self.recovery_seconds - elapsed)
            state = CircuitState.HALF_OPEN if retry_after == 0 else CircuitState.OPEN
        return CircuitSnapshot(state, self.consecutive_failures, retry_after)


_NON_RETRYABLE_CODE_PARTS = (
    "INVALID",
    "NOT_ALLOWED",
    "OUTSIDE_ALLOWED",
    "NOT_FOUND",
    "NOT_AVAILABLE",
    "NOT_CONFIGURED",
    "UNSUPPORTED",
    "UNSAFE",
    "TOO_LARGE",
    "BINARY_LOG_REJECTED",
)


def is_retryable_connector_error(error: ConnectorError) -> bool:
    return not any(part in error.code for part in _NON_RETRYABLE_CODE_PARTS)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    base_seconds: float
    max_seconds: float
    jitter_ratio: float

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("Retry max attempts must be positive")
        if self.base_seconds <= 0 or self.max_seconds <= 0:
            raise ValueError("Retry delays must be positive")
        if self.base_seconds > self.max_seconds:
            raise ValueError("Retry base delay cannot exceed maximum delay")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("Retry jitter ratio must be between zero and one")

    def delay(self, failure_number: int, random_sample: float) -> float:
        bounded_sample = min(1.0, max(0.0, random_sample))
        exponential: float = min(
            self.max_seconds,
            self.base_seconds * (2.0 ** max(0, failure_number - 1)),
        )
        factor: float = 1 - self.jitter_ratio + (2 * self.jitter_ratio * bounded_sample)
        return exponential * factor
