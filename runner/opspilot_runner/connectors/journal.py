import asyncio
import re
from collections.abc import Sequence
from typing import Any

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.safety import redact, truncate_utf8

_UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")


class JournalConnectorError(ConnectorError):
    pass


class JournalConnector(ReadOnlyConnector):
    name = "journal"

    def __init__(
        self,
        allowed_units: list[str],
        *,
        max_output_bytes: int = 65536,
        command: str = "journalctl",
    ) -> None:
        invalid = [unit for unit in allowed_units if not _UNIT.fullmatch(unit)]
        if invalid:
            raise ValueError("Configured journal units contain invalid names")
        self.allowed_units = frozenset(allowed_units)
        self.max_output_bytes = max_output_bytes
        self.command = command

    @property
    def observe_operations(self) -> tuple[str, ...]:
        return ("journal.query",)

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        arguments = self._arguments(operation, parameters)
        output = await self._run(arguments, timeout_seconds)
        safe_output, redacted = redact(output)
        bounded_output, truncated = truncate_utf8(safe_output, self.max_output_bytes)
        return ExecutionResult(
            summary=f"Collected {len(bounded_output.splitlines())} bounded journal lines",
            output=bounded_output,
            redacted=redacted,
            truncated=truncated,
        )

    def _arguments(self, operation: str, parameters: dict[str, Any]) -> list[str]:
        if operation != "journal.query":
            raise JournalConnectorError(
                "UNSUPPORTED_JOURNAL_OPERATION",
                f"Unsupported journal operation: {operation}",
            )
        unexpected = set(parameters) - {"unit", "lines", "sinceMinutes", "priority"}
        if unexpected:
            raise JournalConnectorError(
                "INVALID_JOURNAL_PARAMETERS",
                f"Unsupported parameters: {', '.join(sorted(unexpected))}",
            )
        unit = parameters.get("unit")
        if not isinstance(unit, str) or not _UNIT.fullmatch(unit):
            raise JournalConnectorError("INVALID_JOURNAL_UNIT", "Invalid journal unit")
        if unit not in self.allowed_units:
            raise JournalConnectorError(
                "JOURNAL_UNIT_NOT_ALLOWED",
                "Journal unit is not allowlisted",
            )
        lines = parameters.get("lines", 200)
        since_minutes = parameters.get("sinceMinutes", 30)
        priority = parameters.get("priority")
        if not isinstance(lines, int) or isinstance(lines, bool) or not 1 <= lines <= 2000:
            raise JournalConnectorError(
                "INVALID_JOURNAL_PARAMETERS",
                "lines must be between 1 and 2000",
            )
        if (
            not isinstance(since_minutes, int)
            or isinstance(since_minutes, bool)
            or not 1 <= since_minutes <= 1440
        ):
            raise JournalConnectorError(
                "INVALID_JOURNAL_PARAMETERS",
                "sinceMinutes must be between 1 and 1440",
            )
        arguments = [
            "--unit",
            unit,
            "--since",
            f"-{since_minutes} minutes",
            "--lines",
            str(lines),
            "--no-pager",
            "--output",
            "short-iso",
        ]
        if priority is not None:
            valid_priority = (
                isinstance(priority, int) and not isinstance(priority, bool) and 0 <= priority <= 7
            )
            if not valid_priority:
                raise JournalConnectorError(
                    "INVALID_JOURNAL_PARAMETERS",
                    "priority must be between 0 and 7",
                )
            arguments.extend(["--priority", str(priority)])
        return arguments

    async def _run(self, arguments: Sequence[str], timeout_seconds: int) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self.command,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise JournalConnectorError("JOURNALCTL_UNAVAILABLE", str(exc)) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(1, min(timeout_seconds, 300)),
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise JournalConnectorError("JOURNAL_QUERY_TIMEOUT", "Journal query timed out") from exc
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode != 0:
            safe_error, _ = redact(stderr.decode(errors="replace"))
            raise JournalConnectorError(
                "JOURNAL_QUERY_FAILED",
                safe_error[:1000] or f"journalctl exited with {process.returncode}",
            )
        return stdout.decode(errors="replace").strip()
