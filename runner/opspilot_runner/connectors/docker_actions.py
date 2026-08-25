import asyncio
import json
import re
from collections.abc import Sequence
from typing import Any

from opspilot_runner.contracts import ActionConnector, ActionResult, ConnectorError
from opspilot_runner.safety import redact

_CONTAINER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class DockerActionError(ConnectorError):
    pass


class DockerActionConnector(ActionConnector):
    """Small, explicit Docker write allowlist. No shell or arbitrary arguments."""

    name = "docker"
    _operations = ("container.restart", "health.check")

    def __init__(self, *, command: str = "docker") -> None:
        self.command = command

    @property
    def action_operations(self) -> tuple[str, ...]:
        return self._operations

    async def execute_action(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ActionResult:
        arguments, target = self._arguments(operation, parameters)
        stdout = await self._run(arguments, timeout_seconds)
        if operation == "container.restart":
            return ActionResult(summary=f"Container {target} restart request completed")
        return self._health_result(target, stdout)

    @classmethod
    def _arguments(cls, operation: str, parameters: dict[str, Any]) -> tuple[list[str], str]:
        if operation == "container.restart":
            cls._only_keys(parameters, {"containerId"})
            target = cls._target(parameters.get("containerId"), "containerId")
            return ["container", "restart", "--time", "10", target], target
        if operation == "health.check":
            cls._only_keys(parameters, {"target"})
            target = cls._target(parameters.get("target"), "target")
            return [
                "inspect",
                "--type",
                "container",
                "--format",
                "{{json .State}}",
                target,
            ], target
        raise DockerActionError(
            "ACTION_CAPABILITY_NOT_AVAILABLE",
            f"Docker Action capability is not advertised: {operation}",
        )

    async def _run(self, arguments: Sequence[str], timeout_seconds: int) -> str:
        timeout = max(1, min(timeout_seconds, 900))
        try:
            process = await asyncio.create_subprocess_exec(
                self.command,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise DockerActionError("DOCKER_CLI_UNAVAILABLE", "Docker CLI is unavailable") from exc
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise DockerActionError("ACTION_TIMEOUT", "Docker Action timed out") from exc
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()
        if process.returncode != 0:
            safe_error, _ = redact(stderr or stdout)
            raise DockerActionError(
                "DOCKER_ACTION_FAILED",
                safe_error[:1000] or f"Docker CLI exited with {process.returncode}",
            )
        return stdout

    @staticmethod
    def _health_result(target: str, stdout: str) -> ActionResult:
        try:
            state = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise DockerActionError(
                "INVALID_DOCKER_RESPONSE", "Docker returned malformed state"
            ) from exc
        if not isinstance(state, dict):
            raise DockerActionError(
                "INVALID_DOCKER_RESPONSE", "Docker returned an unexpected state"
            )
        status = str(state.get("Status", "unknown"))
        health = state.get("Health")
        health_status = (
            str(health.get("Status", "unknown")) if isinstance(health, dict) else "not-configured"
        )
        if status != "running" or health_status == "unhealthy":
            raise DockerActionError(
                "HEALTH_CHECK_FAILED",
                f"Container {target} status={status}, health={health_status}",
            )
        return ActionResult(summary=f"Container {target} status={status}, health={health_status}")

    @staticmethod
    def _target(value: object, field: str) -> str:
        if not isinstance(value, str) or not _CONTAINER_ID.fullmatch(value):
            raise DockerActionError(
                "INVALID_ACTION_TARGET",
                f"{field} must be a Docker container ID or name without option characters",
            )
        return value

    @staticmethod
    def _only_keys(parameters: dict[str, Any], allowed: set[str]) -> None:
        if set(parameters) != allowed:
            raise DockerActionError(
                "INVALID_ACTION_PARAMETERS",
                f"Action requires exactly: {', '.join(sorted(allowed))}",
            )
