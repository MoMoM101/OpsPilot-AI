import asyncio
import json
import time
from typing import Any

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.target_policy import ProbeTargetPolicy, TargetPolicyError


class TcpProbeError(ConnectorError):
    pass


class TcpProbeConnector(ReadOnlyConnector):
    name = "tcp"

    def __init__(self, policy: ProbeTargetPolicy) -> None:
        self.policy = policy

    @property
    def observe_operations(self) -> tuple[str, ...]:
        return ("tcp.probe",)

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        host, port = self._validate(operation, parameters)
        started = time.perf_counter()
        writer: asyncio.StreamWriter | None = None
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=max(1, min(timeout_seconds, 300)),
            )
            payload: dict[str, Any] = {
                "reachable": True,
                "latencyMs": round((time.perf_counter() - started) * 1000, 2),
            }
        except (TimeoutError, OSError) as exc:
            payload = {
                "reachable": False,
                "latencyMs": round((time.perf_counter() - started) * 1000, 2),
                "errorType": type(exc).__name__,
            }
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        output = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return ExecutionResult(
            summary=f"TCP probe reachable={str(payload['reachable']).lower()}",
            output=output,
            redacted=False,
            truncated=False,
        )

    def _validate(self, operation: str, parameters: dict[str, Any]) -> tuple[str, int]:
        if operation != "tcp.probe":
            raise TcpProbeError("UNSUPPORTED_TCP_OPERATION", "Unsupported TCP operation")
        if set(parameters) - {"host", "port"}:
            raise TcpProbeError("INVALID_TCP_PARAMETERS", "Unsupported TCP parameters")
        host = parameters.get("host")
        port = parameters.get("port")
        if not isinstance(host, str) or not isinstance(port, int) or isinstance(port, bool):
            raise TcpProbeError("INVALID_TCP_PARAMETERS", "A host and port are required")
        try:
            normalized = self.policy.validate(host, port)
        except TargetPolicyError as exc:
            raise TcpProbeError("TCP_TARGET_NOT_ALLOWED", str(exc)) from exc
        return normalized, port
