import asyncio
from pathlib import Path
from typing import Any

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.safety import redact, truncate_utf8


class FileLogConnectorError(ConnectorError):
    pass


class FileLogConnector(ReadOnlyConnector):
    name = "file"

    def __init__(self, allowed_roots: list[Path], *, max_output_bytes: int = 65536) -> None:
        self.allowed_roots = tuple(root.resolve() for root in allowed_roots)
        self.max_output_bytes = max_output_bytes

    @property
    def observe_operations(self) -> tuple[str, ...]:
        return ("file.tail",)

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        if operation != "file.tail":
            raise FileLogConnectorError(
                "UNSUPPORTED_FILE_OPERATION",
                f"Unsupported file operation: {operation}",
            )
        unexpected = set(parameters) - {"path", "lines"}
        if unexpected:
            raise FileLogConnectorError(
                "INVALID_FILE_PARAMETERS",
                f"Unsupported parameters: {', '.join(sorted(unexpected))}",
            )
        path = self._safe_path(parameters.get("path"))
        lines = parameters.get("lines", 200)
        if not isinstance(lines, int) or isinstance(lines, bool) or not 1 <= lines <= 2000:
            raise FileLogConnectorError(
                "INVALID_FILE_PARAMETERS",
                "lines must be an integer between 1 and 2000",
            )
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._read_tail, path, lines),
                timeout=max(1, min(timeout_seconds, 300)),
            )
        except TimeoutError as exc:
            raise FileLogConnectorError("FILE_READ_TIMEOUT", "Log file read timed out") from exc
        except OSError as exc:
            raise FileLogConnectorError("FILE_READ_FAILED", "Log file could not be read") from exc
        if b"\x00" in raw:
            raise FileLogConnectorError("BINARY_LOG_REJECTED", "Binary log content is not allowed")
        content = raw.decode(errors="replace")
        safe_content, redacted = redact(content)
        output, truncated = truncate_utf8(safe_content, self.max_output_bytes)
        return ExecutionResult(
            summary=f"Collected {len(output.splitlines())} bounded file log lines",
            output=output,
            redacted=redacted,
            truncated=truncated,
        )

    def _safe_path(self, value: Any) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise FileLogConnectorError("INVALID_LOG_PATH", "A log path is required")
        if not self.allowed_roots:
            raise FileLogConnectorError(
                "FILE_CONNECTOR_NOT_CONFIGURED",
                "No log roots are configured",
            )
        try:
            path = Path(value).resolve(strict=True)
        except OSError as exc:
            raise FileLogConnectorError("LOG_FILE_NOT_FOUND", "Log file does not exist") from exc
        if not path.is_file():
            raise FileLogConnectorError("INVALID_LOG_PATH", "Log path is not a regular file")
        if not any(path.is_relative_to(root) for root in self.allowed_roots):
            raise FileLogConnectorError(
                "LOG_PATH_OUTSIDE_ALLOWED_ROOTS",
                "Log path is outside configured roots",
            )
        return path

    def _read_tail(self, path: Path, lines: int) -> bytes:
        read_limit = max(self.max_output_bytes * 4, 65536)
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - read_limit))
            content = stream.read(read_limit)
        return b"\n".join(content.splitlines()[-lines:])
