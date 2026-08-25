import asyncio
import math
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from opspilot_runner.config import RunnerSettings
from opspilot_runner.connectors import (
    DockerActionConnector,
    DockerReadOnlyConnector,
    FileLogConnector,
    HostSnapshotConnector,
    HttpProbeConnector,
    JournalConnector,
    PrometheusConnector,
    QdrantConnector,
    RagBusinessHealthConnector,
    SQLiteConnector,
    TcpProbeConnector,
)
from opspilot_runner.contracts import (
    ActionConnector,
    ActionResult,
    ConnectorError,
    ExecutionResult,
    ReadOnlyConnector,
)
from opspilot_runner.reliability import (
    CircuitSnapshot,
    ConnectorCircuitBreaker,
    RetryPolicy,
    is_retryable_connector_error,
)
from opspilot_runner.target_policy import ProbeTargetPolicy


class ConnectorRegistry:
    def __init__(
        self,
        settings: RunnerSettings,
        *,
        connectors: list[ReadOnlyConnector] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_sample: Callable[[], float] = random.random,
    ) -> None:
        configured_connectors: list[ReadOnlyConnector] = [
            DockerReadOnlyConnector(max_output_bytes=settings.max_output_bytes),
            HostSnapshotConnector(max_output_bytes=settings.max_output_bytes),
        ]
        if connectors is None and settings.log_allowed_roots:
            configured_connectors.append(
                FileLogConnector(
                    settings.log_allowed_roots,
                    max_output_bytes=settings.max_output_bytes,
                )
            )
        if connectors is None and settings.journal_allowed_units:
            configured_connectors.append(
                JournalConnector(
                    settings.journal_allowed_units,
                    max_output_bytes=settings.max_output_bytes,
                )
            )
        if connectors is None and settings.sqlite_allowed_roots:
            configured_connectors.append(
                SQLiteConnector(
                    settings.sqlite_allowed_roots,
                    max_output_bytes=settings.max_output_bytes,
                )
            )
        if connectors is None and settings.probe_allowed_hosts and settings.probe_allowed_ports:
            policy = ProbeTargetPolicy(
                settings.probe_allowed_hosts,
                settings.probe_allowed_ports,
            )
            configured_connectors.extend(
                [
                    HttpProbeConnector(
                        policy,
                        max_output_bytes=settings.max_output_bytes,
                    ),
                    TcpProbeConnector(policy),
                    PrometheusConnector(
                        policy,
                        max_output_bytes=settings.max_output_bytes,
                    ),
                    QdrantConnector(
                        policy,
                        max_output_bytes=settings.max_output_bytes,
                    ),
                    RagBusinessHealthConnector(
                        policy,
                        max_output_bytes=settings.max_output_bytes,
                    ),
                ]
            )
        if connectors is not None:
            configured_connectors = connectors
        self.connectors = {connector.name: connector for connector in configured_connectors}
        self.clock = clock
        self.sleeper = sleeper
        self.random_sample = random_sample
        self.retry_policy = RetryPolicy(
            max_attempts=settings.connector_retry_max_attempts,
            base_seconds=settings.connector_retry_base_seconds,
            max_seconds=settings.connector_retry_max_seconds,
            jitter_ratio=settings.connector_retry_jitter_ratio,
        )
        self.circuits = {
            connector.name: ConnectorCircuitBreaker(
                failure_threshold=settings.connector_circuit_failure_threshold,
                recovery_seconds=settings.connector_circuit_recovery_seconds,
                clock=clock,
            )
            for connector in configured_connectors
        }
        action_connectors: list[ActionConnector] = [DockerActionConnector()]
        self.action_connectors = {connector.name: connector for connector in action_connectors}

    def capabilities(self) -> list[dict[str, Any]]:
        return [
            {
                "connector": connector.name,
                "contractVersion": "1.0",
                "observe": list(connector.observe_operations),
                "actions": list(self.action_connectors[connector.name].action_operations)
                if connector.name in self.action_connectors
                else [],
            }
            for connector in self.connectors.values()
        ]

    async def execute(
        self,
        connector_name: str,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: float,
    ) -> ExecutionResult:
        connector = self.connectors.get(connector_name)
        if connector is None:
            raise ConnectorError(
                "CONNECTOR_NOT_AVAILABLE",
                f"Connector is not configured: {connector_name}",
            )
        if operation not in connector.observe_operations:
            raise ConnectorError(
                "CONNECTOR_OPERATION_NOT_AVAILABLE",
                f"Connector does not advertise operation: {operation}",
            )
        circuit = self.circuits[connector_name]
        half_open_probe = circuit.before_call(connector_name)
        deadline = self.clock() + timeout_seconds
        max_attempts = 1 if half_open_probe else self.retry_policy.max_attempts
        try:
            for attempt in range(1, max_attempts + 1):
                remaining = deadline - self.clock()
                if remaining <= 0:
                    error = ConnectorError(
                        "CONNECTOR_TIMEOUT",
                        "Read-only connector query timed out",
                    )
                else:
                    try:
                        async with asyncio.timeout(remaining):
                            result = await connector.execute(
                                operation,
                                parameters,
                                max(1, math.ceil(remaining)),
                            )
                    except TimeoutError:
                        error = ConnectorError(
                            "CONNECTOR_TIMEOUT",
                            "Read-only connector query timed out",
                        )
                    except ConnectorError as exc:
                        error = exc
                    except Exception:
                        circuit.record_failure(retryable=True)
                        raise
                    else:
                        circuit.record_success()
                        return result

                retryable = is_retryable_connector_error(error)
                if not retryable or attempt >= max_attempts:
                    circuit.record_failure(retryable=retryable)
                    raise error
                delay = self.retry_policy.delay(attempt, self.random_sample())
                if delay >= deadline - self.clock():
                    circuit.record_failure(retryable=True)
                    raise error
                await self.sleeper(delay)
        except asyncio.CancelledError:
            circuit.abandon_call()
            raise
        raise RuntimeError("Connector retry loop exited without a result")

    def circuit_snapshot(self, connector_name: str) -> CircuitSnapshot | None:
        circuit = self.circuits.get(connector_name)
        return circuit.snapshot() if circuit is not None else None

    async def execute_action(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ActionResult:
        for connector in self.action_connectors.values():
            if operation in connector.action_operations:
                return await connector.execute_action(operation, parameters, timeout_seconds)
        raise ConnectorError(
            "ACTION_CAPABILITY_NOT_AVAILABLE",
            f"Runner does not advertise Action capability: {operation}",
        )
