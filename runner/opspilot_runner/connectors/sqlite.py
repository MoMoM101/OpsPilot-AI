import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.safety import truncate_utf8


class SQLiteConnectorError(ConnectorError):
    pass


class SQLiteConnector(ReadOnlyConnector):
    name = "sqlite"
    _operations = (
        "sqlite.health",
        "sqlite.lock_status",
        "sqlite.integrity_check",
    )

    def __init__(self, allowed_roots: list[Path], *, max_output_bytes: int = 65536) -> None:
        self.allowed_roots = tuple(root.resolve() for root in allowed_roots)
        self.max_output_bytes = max_output_bytes

    @property
    def observe_operations(self) -> tuple[str, ...]:
        return self._operations

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        path = self._validate(operation, parameters)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(self._inspect, operation, path),
                timeout=max(1, min(timeout_seconds, 300)),
            )
        except TimeoutError as exc:
            raise SQLiteConnectorError(
                "SQLITE_QUERY_TIMEOUT", "SQLite diagnostic timed out"
            ) from exc
        output, truncated = truncate_utf8(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            self.max_output_bytes,
        )
        return ExecutionResult(
            summary=self._summary(operation, payload),
            output=output,
            redacted=False,
            truncated=truncated,
        )

    def _validate(self, operation: str, parameters: dict[str, Any]) -> Path:
        if operation not in self._operations:
            raise SQLiteConnectorError(
                "UNSUPPORTED_SQLITE_OPERATION", "Unsupported SQLite operation"
            )
        if set(parameters) != {"path"} or not isinstance(parameters.get("path"), str):
            raise SQLiteConnectorError(
                "INVALID_SQLITE_PARAMETERS", "SQLite operation requires only path"
            )
        try:
            path = Path(parameters["path"]).resolve(strict=True)
        except OSError as exc:
            raise SQLiteConnectorError(
                "SQLITE_FILE_NOT_FOUND", "SQLite database file does not exist"
            ) from exc
        if not path.is_file():
            raise SQLiteConnectorError("INVALID_SQLITE_PATH", "SQLite path is not a regular file")
        if not any(self._within(path, root) for root in self.allowed_roots):
            raise SQLiteConnectorError(
                "SQLITE_PATH_NOT_ALLOWED", "SQLite path is outside configured roots"
            )
        return path

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _inspect(operation: str, path: Path) -> dict[str, Any]:
        started = time.perf_counter()
        uri = f"{path.as_uri()}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=0.05) as connection:
                connection.execute("PRAGMA query_only=ON")
                if operation == "sqlite.health":
                    version = str(connection.execute("SELECT sqlite_version()").fetchone()[0])
                    schema_objects = int(
                        connection.execute(
                            "SELECT count(*) FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
                        ).fetchone()[0]
                    )
                    return {
                        "accessible": True,
                        "healthy": True,
                        "sqliteVersion": version[:50],
                        "schemaObjectCount": schema_objects,
                        "latencyMs": round((time.perf_counter() - started) * 1000, 2),
                    }
                if operation == "sqlite.lock_status":
                    journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
                    locking_mode = str(connection.execute("PRAGMA locking_mode").fetchone()[0])
                    connection.execute("SELECT 1").fetchone()
                    return {
                        "accessible": True,
                        "locked": False,
                        "journalMode": journal_mode[:30],
                        "lockingMode": locking_mode[:30],
                        "walFilePresent": path.with_name(path.name + "-wal").exists(),
                        "latencyMs": round((time.perf_counter() - started) * 1000, 2),
                    }
                rows = connection.execute("PRAGMA integrity_check(100)").fetchmany(100)
                messages = [str(row[0])[:500] for row in rows]
                healthy = messages == ["ok"]
                return {
                    "accessible": True,
                    "healthy": healthy,
                    "result": messages,
                    "resultTruncated": len(rows) >= 100 and not healthy,
                    "latencyMs": round((time.perf_counter() - started) * 1000, 2),
                }
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                return {
                    "accessible": False,
                    "healthy": False,
                    "locked": True,
                    "errorType": "database_locked",
                    "latencyMs": round((time.perf_counter() - started) * 1000, 2),
                }
            raise SQLiteConnectorError(
                "SQLITE_READ_FAILED", "SQLite database could not be read"
            ) from exc
        except sqlite3.DatabaseError as exc:
            raise SQLiteConnectorError(
                "SQLITE_INVALID_DATABASE", "SQLite database is invalid or unreadable"
            ) from exc

    @staticmethod
    def _summary(operation: str, payload: dict[str, Any]) -> str:
        if payload.get("locked") is True:
            return "SQLite database is locked or busy"
        if operation == "sqlite.integrity_check":
            return f"SQLite integrity healthy={str(payload.get('healthy') is True).lower()}"
        return f"SQLite {operation.rpartition('.')[2]} completed"
