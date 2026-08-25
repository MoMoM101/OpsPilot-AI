from typing import Any

import pytest

from opspilot_runner.config import RunnerSettings
from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.registry import ConnectorRegistry
from opspilot_runner.reliability import (
    CircuitState,
    RetryPolicy,
    is_retryable_connector_error,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 10.0
        self.delays: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _SequenceConnector(ReadOnlyConnector):
    name = "sequence"
    observe_operations = ("sequence.read",)

    def __init__(self, outcomes: list[ExecutionResult | ConnectorError]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, ConnectorError):
            raise outcome
        return outcome


def _result() -> ExecutionResult:
    return ExecutionResult("recovered", "{}", False, False)


def _registry(
    connector: ReadOnlyConnector,
    clock: _Clock,
    *,
    attempts: int = 3,
    threshold: int = 2,
) -> ConnectorRegistry:
    settings = RunnerSettings(
        connector_retry_max_attempts=attempts,
        connector_retry_base_seconds=1,
        connector_retry_max_seconds=4,
        connector_retry_jitter_ratio=0.25,
        connector_circuit_failure_threshold=threshold,
        connector_circuit_recovery_seconds=10,
    )
    return ConnectorRegistry(
        settings,
        connectors=[connector],
        clock=clock,
        sleeper=clock.sleep,
        random_sample=lambda: 0.5,
    )


@pytest.mark.asyncio
async def test_transient_failures_retry_with_exponential_backoff_inside_total_budget() -> None:
    clock = _Clock()
    connector = _SequenceConnector(
        [
            ConnectorError("SEQUENCE_UNAVAILABLE", "first"),
            ConnectorError("SEQUENCE_UNAVAILABLE", "second"),
            _result(),
        ]
    )
    registry = _registry(connector, clock)

    result = await registry.execute("sequence", "sequence.read", {}, 10)

    assert result == _result()
    assert connector.calls == 3
    assert clock.delays == [1, 2]
    snapshot = registry.circuit_snapshot("sequence")
    assert snapshot is not None
    assert snapshot.state == CircuitState.CLOSED
    assert snapshot.consecutive_failures == 0


@pytest.mark.asyncio
async def test_non_retryable_error_fails_immediately_without_sleeping_or_tripping_circuit() -> None:
    clock = _Clock()
    connector = _SequenceConnector(
        [ConnectorError("INVALID_SEQUENCE_ARGUMENT", "invalid")]
    )
    registry = _registry(connector, clock, threshold=1)

    with pytest.raises(ConnectorError) as error:
        await registry.execute("sequence", "sequence.read", {}, 10)

    assert error.value.code == "INVALID_SEQUENCE_ARGUMENT"
    assert connector.calls == 1
    assert clock.delays == []
    snapshot = registry.circuit_snapshot("sequence")
    assert snapshot is not None
    assert snapshot.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_exhausted_retry_group_counts_as_one_circuit_failure() -> None:
    clock = _Clock()
    connector = _SequenceConnector(
        [ConnectorError("SEQUENCE_FAILED", "down") for _ in range(3)]
    )
    registry = _registry(connector, clock, threshold=2)

    with pytest.raises(ConnectorError):
        await registry.execute("sequence", "sequence.read", {}, 10)

    snapshot = registry.circuit_snapshot("sequence")
    assert snapshot is not None
    assert snapshot.state == CircuitState.CLOSED
    assert snapshot.consecutive_failures == 1
    assert connector.calls == 3


@pytest.mark.asyncio
async def test_half_open_probe_uses_one_attempt_and_reopens_on_failure() -> None:
    clock = _Clock()
    connector = _SequenceConnector(
        [
            ConnectorError("SEQUENCE_FAILED", "one"),
            ConnectorError("SEQUENCE_FAILED", "two"),
            ConnectorError("SEQUENCE_FAILED", "three"),
            ConnectorError("SEQUENCE_FAILED", "probe"),
        ]
    )
    registry = _registry(connector, clock, threshold=1)

    with pytest.raises(ConnectorError):
        await registry.execute("sequence", "sequence.read", {}, 10)
    assert connector.calls == 3
    clock.advance(10)
    with pytest.raises(ConnectorError, match="probe"):
        await registry.execute("sequence", "sequence.read", {}, 10)

    assert connector.calls == 4
    reopened = registry.circuit_snapshot("sequence")
    assert reopened is not None
    assert reopened.state == CircuitState.OPEN
    assert reopened.retry_after_seconds == 10


@pytest.mark.asyncio
async def test_retry_stops_when_backoff_would_exceed_total_timeout_budget() -> None:
    clock = _Clock()
    connector = _SequenceConnector(
        [ConnectorError("SEQUENCE_UNAVAILABLE", "down")]
    )
    registry = _registry(connector, clock)

    with pytest.raises(ConnectorError):
        await registry.execute("sequence", "sequence.read", {}, 1)

    assert connector.calls == 1
    assert clock.delays == []


def test_retry_policy_applies_bounded_symmetric_jitter() -> None:
    policy = RetryPolicy(
        max_attempts=3,
        base_seconds=2,
        max_seconds=10,
        jitter_ratio=0.25,
    )

    assert policy.delay(1, 0) == 1.5
    assert policy.delay(1, 0.5) == 2
    assert policy.delay(1, 1) == 2.5
    assert policy.delay(4, 0.5) == 10


@pytest.mark.parametrize(
    "code",
    [
        "INVALID_QDRANT_PARAMETERS",
        "RAG_TARGET_NOT_ALLOWED",
        "LOG_PATH_OUTSIDE_ALLOWED_ROOTS",
        "SQLITE_FILE_NOT_FOUND",
        "FILE_CONNECTOR_NOT_CONFIGURED",
        "UNSUPPORTED_HTTP_OPERATION",
        "UNSAFE_PROMETHEUS_URL",
        "QDRANT_RESPONSE_TOO_LARGE",
    ],
)
def test_deterministic_or_policy_errors_are_not_retryable(code: str) -> None:
    assert is_retryable_connector_error(ConnectorError(code, "error")) is False


@pytest.mark.parametrize(
    "code",
    [
        "QDRANT_UNAVAILABLE",
        "RAG_UNAVAILABLE",
        "SQLITE_QUERY_TIMEOUT",
        "JOURNAL_QUERY_FAILED",
    ],
)
def test_transient_dependency_errors_are_retryable(code: str) -> None:
    assert is_retryable_connector_error(ConnectorError(code, "error")) is True
