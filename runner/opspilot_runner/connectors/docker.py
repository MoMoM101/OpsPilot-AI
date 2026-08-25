import asyncio
import json
import re
from collections.abc import Sequence
from typing import Any

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.safety import redact, truncate_utf8

_CONTAINER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SINCE = re.compile(
    r"^(?:\d+(?:\.\d+)?(?:ns|us|ms|s|m|h)|"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))$"
)


class DockerConnectorError(ConnectorError):
    pass


class DockerReadOnlyConnector(ReadOnlyConnector):
    name = "docker"
    _operations = (
        "docker.list_containers",
        "docker.inspect_container",
        "docker.container_logs",
        "docker.container_health",
    )

    def __init__(self, *, max_output_bytes: int = 65536, command: str = "docker") -> None:
        self.max_output_bytes = max_output_bytes
        self.command = command

    @property
    def observe_operations(self) -> tuple[str, ...]:
        return self._operations

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        arguments = self._arguments(operation, parameters)
        stdout, stderr = await self._run(arguments, timeout_seconds)
        normalized = self._normalize_output(operation, stdout)
        combined = normalized if not stderr else f"{normalized}\n{stderr}".strip()
        safe_output, redacted = redact(combined)
        bounded_output, truncated = truncate_utf8(safe_output, self.max_output_bytes)
        return ExecutionResult(
            summary=self._summary(operation, stdout),
            output=bounded_output,
            redacted=redacted,
            truncated=truncated,
        )

    def _arguments(self, operation: str, parameters: dict[str, Any]) -> list[str]:
        if operation == "docker.list_containers":
            if parameters:
                raise DockerConnectorError(
                    "INVALID_DOCKER_PARAMETERS",
                    "list_containers does not accept parameters",
                )
            return ["container", "ls", "--all", "--no-trunc", "--format", "{{json .}}"]

        container_id = self._container_id(parameters)
        if operation == "docker.inspect_container":
            self._only_keys(parameters, {"containerId"})
            return [
                "inspect",
                "--type",
                "container",
                "--format",
                "{{json .}}",
                container_id,
            ]
        if operation == "docker.container_health":
            self._only_keys(parameters, {"containerId"})
            return [
                "inspect",
                "--type",
                "container",
                "--format",
                "{{json .State}}",
                container_id,
            ]
        if operation == "docker.container_logs":
            self._only_keys(parameters, {"containerId", "tail", "since", "timestamps"})
            tail = parameters.get("tail", 200)
            if not isinstance(tail, int) or isinstance(tail, bool) or not 1 <= tail <= 2000:
                raise DockerConnectorError(
                    "INVALID_DOCKER_PARAMETERS",
                    "tail must be an integer between 1 and 2000",
                )
            arguments = ["container", "logs", "--tail", str(tail)]
            since = parameters.get("since")
            if since is not None:
                if not isinstance(since, str) or not _SINCE.fullmatch(since):
                    raise DockerConnectorError(
                        "INVALID_DOCKER_PARAMETERS",
                        "since must be a bounded duration or RFC3339 timestamp",
                    )
                arguments.extend(["--since", since])
            if parameters.get("timestamps", True) is not False:
                arguments.append("--timestamps")
            arguments.append(container_id)
            return arguments
        raise DockerConnectorError(
            "UNSUPPORTED_DOCKER_OPERATION",
            f"Unsupported read-only Docker operation: {operation}",
        )

    async def _run(self, arguments: Sequence[str], timeout_seconds: int) -> tuple[str, str]:
        timeout = max(1, min(timeout_seconds, 300))
        try:
            process = await asyncio.create_subprocess_exec(
                self.command,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise DockerConnectorError("DOCKER_CLI_UNAVAILABLE", str(exc)) from exc
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise DockerConnectorError("DOCKER_COMMAND_TIMEOUT", "Docker query timed out") from exc
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()
        if process.returncode != 0:
            safe_error, _ = redact(stderr or stdout)
            raise DockerConnectorError(
                "DOCKER_QUERY_FAILED",
                safe_error[:1000] or f"Docker CLI exited with {process.returncode}",
            )
        return stdout, stderr

    @staticmethod
    def _container_id(parameters: dict[str, Any]) -> str:
        value = parameters.get("containerId")
        if not isinstance(value, str) or not _CONTAINER_ID.fullmatch(value):
            raise DockerConnectorError(
                "INVALID_CONTAINER_ID",
                "containerId must be a container ID or name without option characters",
            )
        return value

    @staticmethod
    def _only_keys(parameters: dict[str, Any], allowed: set[str]) -> None:
        unexpected = set(parameters) - allowed
        if unexpected:
            raise DockerConnectorError(
                "INVALID_DOCKER_PARAMETERS",
                f"Unsupported parameters: {', '.join(sorted(unexpected))}",
            )

    @staticmethod
    def _summary(operation: str, stdout: str) -> str:
        if operation == "docker.list_containers":
            count = sum(1 for line in stdout.splitlines() if line.strip())
            return f"Collected {count} Docker container records"
        if operation == "docker.container_logs":
            count = sum(1 for line in stdout.splitlines() if line.strip())
            return f"Collected {count} bounded Docker log lines"
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return f"Collected {operation} result"
        if operation == "docker.container_health" and isinstance(payload, dict):
            return f"Container status={payload.get('Status', 'unknown')}"
        return "Collected Docker container details"

    @classmethod
    def _normalize_output(cls, operation: str, stdout: str) -> str:
        if operation == "docker.container_logs":
            return stdout
        try:
            if operation == "docker.list_containers":
                records = [json.loads(line) for line in stdout.splitlines() if line.strip()]
                normalized = [
                    cls._select(
                        record,
                        "ID",
                        "Names",
                        "Image",
                        "State",
                        "Status",
                        "Ports",
                        "CreatedAt",
                    )
                    for record in records
                    if isinstance(record, dict)
                ]
                return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise DockerConnectorError(
                "INVALID_DOCKER_RESPONSE",
                "Docker returned malformed JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise DockerConnectorError(
                "INVALID_DOCKER_RESPONSE",
                "Docker returned an unexpected response type",
            )
        if operation == "docker.container_health":
            return json.dumps(
                cls._safe_state(payload),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        state = payload.get("State")
        config = payload.get("Config")
        network_settings = payload.get("NetworkSettings")
        mounts = payload.get("Mounts")
        result: dict[str, Any] = cls._select(
            payload,
            "Id",
            "Name",
            "Created",
            "Image",
            "RestartCount",
        )
        if isinstance(state, dict):
            result["State"] = cls._safe_state(state)
        if isinstance(config, dict):
            result["Config"] = cls._select(config, "Hostname", "Image", "WorkingDir", "User")
        if isinstance(network_settings, dict):
            networks = network_settings.get("Networks")
            result["NetworkSettings"] = {
                "Ports": network_settings.get("Ports", {}),
                "Networks": sorted(networks) if isinstance(networks, dict) else [],
            }
        if isinstance(mounts, list):
            result["Mounts"] = [
                cls._select(mount, "Type", "Destination", "Mode", "RW")
                for mount in mounts
                if isinstance(mount, dict)
            ]
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _safe_state(cls, state: dict[str, Any]) -> dict[str, Any]:
        result = cls._select(
            state,
            "Status",
            "Running",
            "Paused",
            "Restarting",
            "OOMKilled",
            "Dead",
            "Pid",
            "ExitCode",
            "Error",
            "StartedAt",
            "FinishedAt",
        )
        health = state.get("Health")
        if isinstance(health, dict):
            result["Health"] = {
                "Status": health.get("Status", "unknown"),
                "FailingStreak": health.get("FailingStreak", 0),
            }
        return result

    @staticmethod
    def _select(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
        return {key: payload[key] for key in keys if key in payload}
