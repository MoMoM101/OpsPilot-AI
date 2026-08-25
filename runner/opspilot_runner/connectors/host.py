import asyncio
import contextlib
import json
import os
import platform
import shutil
import socket
import time
from pathlib import Path
from typing import Any

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.safety import redact, truncate_utf8


class HostConnectorError(ConnectorError):
    pass


class HostSnapshotConnector(ReadOnlyConnector):
    name = "host"

    def __init__(self, *, max_output_bytes: int = 65536) -> None:
        self.max_output_bytes = max_output_bytes

    @property
    def observe_operations(self) -> tuple[str, ...]:
        return ("host.snapshot",)

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        if operation != "host.snapshot":
            raise HostConnectorError("UNSUPPORTED_HOST_OPERATION", "Unsupported host operation")
        if parameters:
            raise HostConnectorError(
                "INVALID_HOST_PARAMETERS",
                "host.snapshot does not accept parameters",
            )
        try:
            snapshot = await asyncio.wait_for(
                asyncio.to_thread(self._collect),
                timeout=max(1, min(timeout_seconds, 60)),
            )
        except TimeoutError as exc:
            raise HostConnectorError("HOST_SNAPSHOT_TIMEOUT", "Host snapshot timed out") from exc
        output = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        safe_output, redacted = redact(output)
        bounded, truncated = truncate_utf8(safe_output, self.max_output_bytes)
        return ExecutionResult(
            summary=(
                f"Collected host snapshot system={snapshot['platform']['system']} "
                f"cpu={snapshot['cpu']['logicalCount']}"
            ),
            output=bounded,
            redacted=redacted,
            truncated=truncated,
        )

    @classmethod
    def _collect(cls) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "schemaVersion": "1.0",
            "collectedAtUnix": round(time.time(), 3),
            "platform": {
                "system": platform.system(),
                "release": platform.release()[:200],
                "machine": platform.machine()[:100],
                "hostname": socket.gethostname()[:253],
                "pythonVersion": platform.python_version(),
            },
            "cpu": {"logicalCount": os.cpu_count()},
        }
        getloadavg = getattr(os, "getloadavg", None)
        if callable(getloadavg):
            with contextlib.suppress(OSError):
                snapshot["cpu"]["loadAverage"] = [round(value, 4) for value in getloadavg()]
        if snapshot["platform"]["system"] == "Linux":
            memory = cls._linux_memory(Path("/proc/meminfo"))
            if memory:
                snapshot["memory"] = memory
            uptime = cls._linux_uptime(Path("/proc/uptime"))
            if uptime is not None:
                snapshot["uptimeSeconds"] = uptime
            network = cls._linux_network(Path("/proc/net/dev"))
            if network:
                snapshot["network"] = network
            process_count = cls._linux_process_count(Path("/proc"))
            if process_count is not None:
                snapshot["processCount"] = process_count
        root = Path.cwd().anchor or "/"
        try:
            disk = shutil.disk_usage(root)
            snapshot["disk"] = {
                "root": root,
                "totalBytes": disk.total,
                "usedBytes": disk.used,
                "freeBytes": disk.free,
                "usedPercent": round(disk.used / disk.total * 100, 2) if disk.total else 0,
            }
        except OSError:
            pass
        return snapshot

    @staticmethod
    def _linux_memory(path: Path) -> dict[str, int | float]:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return {}
        values: dict[str, int] = {}
        for line in content.splitlines():
            name, separator, raw = line.partition(":")
            if not separator:
                continue
            parts = raw.strip().split()
            if parts and parts[0].isdigit():
                values[name] = int(parts[0]) * 1024
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        if not total or available is None:
            return {}
        used = max(0, total - available)
        return {
            "totalBytes": total,
            "availableBytes": available,
            "usedBytes": used,
            "usedPercent": round(used / total * 100, 2),
        }

    @staticmethod
    def _linux_uptime(path: Path) -> float | None:
        try:
            first = path.read_text(encoding="utf-8").split()[0]
            return round(float(first), 3)
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _linux_network(path: Path) -> list[dict[str, int | str]]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[2:]
        except OSError:
            return []
        result: list[dict[str, int | str]] = []
        for line in lines[:64]:
            interface, separator, raw = line.partition(":")
            fields = raw.split()
            if not separator or len(fields) < 16:
                continue
            try:
                result.append(
                    {
                        "interface": interface.strip()[:64],
                        "receiveBytes": int(fields[0]),
                        "receivePackets": int(fields[1]),
                        "transmitBytes": int(fields[8]),
                        "transmitPackets": int(fields[9]),
                    }
                )
            except ValueError:
                continue
        return result

    @staticmethod
    def _linux_process_count(path: Path) -> int | None:
        if not path.is_dir():
            return None
        try:
            return sum(1 for entry in path.iterdir() if entry.name.isdigit() and entry.is_dir())
        except OSError:
            return None
