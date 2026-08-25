import asyncio
from typing import Any

import pytest

from opspilot_runner.config import RunnerSettings
from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.registry import ConnectorRegistry
from opspilot_runner.reliability import CircuitState, ConnectorCircuitBreaker


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _StubConnector(ReadOnlyConnector):
    name = "stub"
    observe_operations = ("stub.read",)

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
    return ExecutionResult("ok", "{}", False, False)


def _registry(
    connector: ReadOnlyConnector,
    clock: _Clock,
    *,
    threshold: int = 2,
    recovery_seconds: float = 10,
) -> ConnectorRegistry:
    return ConnectorRegistry(
        RunnerSettings(
            connector_circuit_failure_threshold=threshold,
            connector_circuit_recovery_seconds=recovery_seconds,
            connector_retry_max_attempts=1,
        ),
        connectors=[connector],
        clock=clock,
    )


@pytest.mark.asyncio
async def test_retryable_failures_open_then_successfully_close_the_circuit() -> None:
    clock = _Clock()
    connector = _StubConnector(
        [
            ConnectorError("STUB_UNAVAILABLE", "down"),
            ConnectorError("STUB_UNAVAILABLE", "down"),
            _result(),
        ]
    )
    registry = _registry(connector, clock)

    for _ in range(2):
        with pytest.raises(ConnectorError, match="down"):
            await registry.execute("stub", "stub.read", {}, 5)

    snapshot = registry.circuit_snapshot("stub")
    assert snapshot is not None
    assert snapshot.state == CircuitState.OPEN
    assert snapshot.consecutive_failures == 2
    with pytest.raises(ConnectorError) as open_error:
        await registry.execute("stub", "stub.read", {}, 5)
    assert open_error.value.code == "CONNECTOR_CIRCUIT_OPEN"
    assert connector.calls == 2

    clock.advance(10)
    assert await registry.execute("stub", "stub.read", {}, 5) == _result()
    recovered = registry.circuit_snapshot("stub")
    assert recovered is not None
    assert recovered.state == CircuitState.CLOSED
    assert recovered.consecutive_failures == 0


@pytest.mark.asyncio
async def test_failed_half_open_probe_reopens_for_a_full_recovery_interval() -> None:
    clock = _Clock()
    connector = _StubConnector(
        [
            ConnectorError("STUB_FAILED", "first"),
            ConnectorError("STUB_FAILED", "probe"),
        ]
    )
    registry = _registry(connector, clock, threshold=1)

    with pytest.raises(ConnectorError):
        await registry.execute("stub", "stub.read", {}, 5)
    clock.advance(10)
    with pytest.raises(ConnectorError, match="probe"):
        await registry.execute("stub", "stub.read", {}, 5)

    reopened = registry.circuit_snapshot("stub")
    assert reopened is not None
    assert reopened.state == CircuitState.OPEN
    assert reopened.retry_after_seconds == 10


@pytest.mark.asyncio
async def test_invalid_or_disallowed_requests_do_not_trip_dependency_circuit() -> None:
    clock = _Clock()
    connector = _StubConnector(
        [
            ConnectorError("INVALID_STUB_ARGUMENT", "invalid"),
            ConnectorError("STUB_TARGET_NOT_ALLOWED", "denied"),
            _result(),
        ]
    )
    registry = _registry(connector, clock, threshold=1)

    for _ in range(2):
        with pytest.raises(ConnectorError):
            await registry.execute("stub", "stub.read", {}, 5)
    assert await registry.execute("stub", "stub.read", {}, 5) == _result()
    snapshot = registry.circuit_snapshot("stub")
    assert snapshot is not None
    assert snapshot.state == CircuitState.CLOSED


class _SlowConnector(ReadOnlyConnector):
    name = "slow"
    observe_operations = ("slow.read",)

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        await asyncio.sleep(1)
        return _result()


@pytest.mark.asyncio
async def test_registry_is_the_timeout_owner_and_counts_timeout_as_failure() -> None:
    clock = _Clock()
    registry = _registry(_SlowConnector(), clock, threshold=1)

    with pytest.raises(ConnectorError) as timeout_error:
        await registry.execute("slow", "slow.read", {}, 0)

    assert timeout_error.value.code == "CONNECTOR_TIMEOUT"
    snapshot = registry.circuit_snapshot("slow")
    assert snapshot is not None
    assert snapshot.state == CircuitState.OPEN


def test_abandoned_half_open_probe_does_not_permanently_block_recovery() -> None:
    clock = _Clock()
    circuit = ConnectorCircuitBreaker(
        failure_threshold=1,
        recovery_seconds=10,
        clock=clock,
    )
    circuit.record_failure(retryable=True)
    clock.advance(10)

    circuit.before_call("stub")
    circuit.abandon_call()
    circuit.before_call("stub")

    assert circuit.snapshot().state == CircuitState.HALF_OPEN
