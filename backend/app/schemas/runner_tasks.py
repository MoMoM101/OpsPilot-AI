import json
import math
import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.runner_tasks import RunnerReadOperation, RunnerTaskStatus
from app.schemas.base import ApiModel


class RunnerTaskCreate(ApiModel):
    incident_id: UUID
    plan_step_id: UUID | None = None
    resource_id: UUID
    runner_id: UUID | None = None
    connector: Literal[
        "docker",
        "file",
        "journal",
        "http",
        "tcp",
        "prometheus",
        "host",
        "sqlite",
        "qdrant",
        "rag",
    ]
    operation: RunnerReadOperation
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=128)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_attempts: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def validate_read_parameters(self) -> "RunnerTaskCreate":
        encoded = json.dumps(self.parameters, separators=(",", ":"), default=str)
        if len(encoded.encode()) > 16384:
            raise ValueError("Task parameters exceed 16 KiB")
        expected_connector = self.operation.value.partition(".")[0]
        if self.connector != expected_connector:
            raise ValueError("connector does not match the requested operation")
        needs_container = self.operation in {
            RunnerReadOperation.INSPECT_CONTAINER,
            RunnerReadOperation.CONTAINER_LOGS,
            RunnerReadOperation.CONTAINER_HEALTH,
        }
        container_id = self.parameters.get("containerId")
        if needs_container and (not isinstance(container_id, str) or not container_id.strip()):
            raise ValueError("containerId is required for this operation")
        if self.operation == RunnerReadOperation.FILE_TAIL:
            path = self.parameters.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("path is required for file.tail")
            self._bounded_lines()
        if self.operation == RunnerReadOperation.JOURNAL_QUERY:
            unit = self.parameters.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                raise ValueError("unit is required for journal.query")
            self._bounded_lines()
            since_minutes = self.parameters.get("sinceMinutes", 30)
            if (
                not isinstance(since_minutes, int)
                or isinstance(since_minutes, bool)
                or not 1 <= since_minutes <= 1440
            ):
                raise ValueError("sinceMinutes must be between 1 and 1440")
        if self.operation == RunnerReadOperation.HTTP_PROBE:
            self._validate_http_probe()
        if self.operation == RunnerReadOperation.TCP_PROBE:
            self._validate_tcp_probe()
        if self.operation in {
            RunnerReadOperation.PROMETHEUS_QUERY,
            RunnerReadOperation.PROMETHEUS_QUERY_RANGE,
        }:
            self._validate_prometheus_query()
        if self.operation == RunnerReadOperation.HOST_SNAPSHOT and self.parameters:
            raise ValueError("host.snapshot does not accept parameters")
        if self.operation in {
            RunnerReadOperation.SQLITE_HEALTH,
            RunnerReadOperation.SQLITE_LOCK_STATUS,
            RunnerReadOperation.SQLITE_INTEGRITY_CHECK,
        }:
            self._validate_sqlite()
        if self.operation in {
            RunnerReadOperation.QDRANT_HEALTH,
            RunnerReadOperation.QDRANT_COLLECTION,
            RunnerReadOperation.QDRANT_POINT_COUNT,
            RunnerReadOperation.QDRANT_QUERY_SMOKE,
        }:
            self._validate_qdrant()
        if self.operation == RunnerReadOperation.RAG_BUSINESS_HEALTH:
            self._validate_rag_business_health()
        return self

    def _validate_sqlite(self) -> None:
        if set(self.parameters) != {"path"}:
            raise ValueError("SQLite operations accept only path")
        path = self.parameters.get("path")
        if not isinstance(path, str) or not path.strip() or len(path) > 4096:
            raise ValueError("SQLite path must contain between 1 and 4096 characters")
        if "\x00" in path:
            raise ValueError("SQLite path contains an invalid character")

    def _validate_qdrant(self) -> None:
        allowed = {"baseUrl"}
        if self.operation != RunnerReadOperation.QDRANT_HEALTH:
            allowed.add("collection")
        if self.operation == RunnerReadOperation.QDRANT_QUERY_SMOKE:
            allowed.update({"vector", "limit"})
        if set(self.parameters) - allowed:
            raise ValueError("Unsupported Qdrant parameters")
        self._validate_service_url(self.parameters.get("baseUrl"), "Qdrant")
        if self.operation == RunnerReadOperation.QDRANT_HEALTH:
            return
        collection = self.parameters.get("collection")
        if not isinstance(collection, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,254}", collection
        ):
            raise ValueError("Qdrant collection name is invalid")
        if self.operation != RunnerReadOperation.QDRANT_QUERY_SMOKE:
            return
        vector = self.parameters.get("vector")
        if (
            not isinstance(vector, list)
            or not 1 <= len(vector) <= 4096
            or any(
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in vector
            )
        ):
            raise ValueError("Qdrant smoke vector must contain 1 to 4096 finite numbers")
        limit = self.parameters.get("limit", 3)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("Qdrant query limit must be between 1 and 20")

    def _validate_rag_business_health(self) -> None:
        if set(self.parameters) - {"url", "question", "expectedTerms"}:
            raise ValueError("Unsupported RAG health parameters")
        self._validate_service_url(self.parameters.get("url"), "RAG")
        question = self.parameters.get("question")
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
            raise ValueError("RAG health question must contain between 1 and 500 characters")
        terms = self.parameters.get("expectedTerms", [])
        if (
            not isinstance(terms, list)
            or len(terms) > 20
            or any(
                not isinstance(term, str) or not 1 <= len(term.strip()) <= 100
                for term in terms
            )
        ):
            raise ValueError("RAG expected terms must contain up to 20 bounded strings")

    @staticmethod
    def _validate_service_url(value: Any, service: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{service} URL is required")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"Only HTTP and HTTPS {service} URLs are supported")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                f"{service} URL credentials, query strings, and fragments are forbidden"
            )

    def _bounded_lines(self) -> None:
        lines = self.parameters.get("lines", 200)
        if not isinstance(lines, int) or isinstance(lines, bool) or not 1 <= lines <= 2000:
            raise ValueError("lines must be between 1 and 2000")

    def _validate_http_probe(self) -> None:
        unexpected = set(self.parameters) - {
            "url",
            "method",
            "expectedStatuses",
            "captureBody",
        }
        if unexpected:
            raise ValueError("Unsupported HTTP probe parameters")
        url = self.parameters.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url is required for http.probe")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only HTTP and HTTPS probe URLs are supported")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("URL credentials, query strings, and fragments are not allowed")
        method = self.parameters.get("method", "GET")
        if method not in {"GET", "HEAD"}:
            raise ValueError("HTTP probe method must be GET or HEAD")
        statuses = self.parameters.get("expectedStatuses", [200])
        if (
            not isinstance(statuses, list)
            or not 1 <= len(statuses) <= 20
            or any(
                not isinstance(item, int) or isinstance(item, bool) or not 100 <= item <= 599
                for item in statuses
            )
        ):
            raise ValueError("expectedStatuses must contain 1 to 20 HTTP status codes")
        if not isinstance(self.parameters.get("captureBody", False), bool):
            raise ValueError("captureBody must be boolean")

    def _validate_tcp_probe(self) -> None:
        unexpected = set(self.parameters) - {"host", "port"}
        if unexpected:
            raise ValueError("Unsupported TCP probe parameters")
        host = self.parameters.get("host")
        port = self.parameters.get("port")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host is required for tcp.probe")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")

    def _validate_prometheus_query(self) -> None:
        common = {"baseUrl", "query"}
        allowed = (
            common | {"time"}
            if self.operation == RunnerReadOperation.PROMETHEUS_QUERY
            else common | {"start", "end", "stepSeconds"}
        )
        if set(self.parameters) - allowed:
            raise ValueError("Unsupported Prometheus query parameters")
        base_url = self.parameters.get("baseUrl")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("baseUrl is required for Prometheus queries")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only HTTP and HTTPS Prometheus URLs are supported")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "Prometheus URL credentials, query strings, and fragments are forbidden"
            )
        query = self.parameters.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError("PromQL query must contain between 1 and 2000 characters")
        if self.operation == RunnerReadOperation.PROMETHEUS_QUERY:
            if "time" in self.parameters:
                self._aware_timestamp(self.parameters["time"], "time")
            return
        start = self._aware_timestamp(self.parameters.get("start"), "start")
        end = self._aware_timestamp(self.parameters.get("end"), "end")
        if end <= start or (end - start).total_seconds() > 21600:
            raise ValueError("Prometheus range must be positive and no longer than 6 hours")
        step = self.parameters.get("stepSeconds", 60)
        if not isinstance(step, int) or isinstance(step, bool) or not 1 <= step <= 3600:
            raise ValueError("stepSeconds must be between 1 and 3600")
        if (end - start).total_seconds() / step > 11000:
            raise ValueError("Prometheus range query exceeds 11000 points per series")

    @staticmethod
    def _aware_timestamp(value: Any, name: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be an RFC3339 timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an RFC3339 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{name} must include a timezone")
        return parsed


class RunnerTaskResponse(ApiModel):
    id: UUID
    incident_id: UUID
    plan_step_id: UUID | None
    action_verification_id: UUID | None
    resource_id: UUID
    runner_id: UUID | None
    connector: str
    operation: str
    status: RunnerTaskStatus
    idempotency_key: str
    timeout_seconds: int
    max_attempts: int
    attempt: int
    lease_expires_at: datetime | None
    task_fencing_token: int | None
    evidence_id: UUID | None
    result_summary: str | None
    error_code: str | None
    output_truncated: bool
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RunnerTaskClaimRequest(ApiModel):
    runner_fencing_token: int = Field(ge=1)


class RunnerTaskExecution(ApiModel):
    id: UUID
    incident_id: UUID
    plan_step_id: UUID | None
    resource_id: UUID
    connector: str
    operation: str
    parameters: dict[str, Any]
    timeout_seconds: int
    attempt: int
    task_fencing_token: int
    lease_expires_at: datetime


class RunnerTaskClaimResponse(ApiModel):
    task: RunnerTaskExecution | None


class RunnerTaskRenewRequest(ApiModel):
    task_fencing_token: int = Field(ge=1)


class RunnerTaskCompleteRequest(ApiModel):
    completion_id: UUID
    task_fencing_token: int = Field(ge=1)
    status: Literal["succeeded", "failed"]
    summary: str = Field(min_length=1, max_length=1000)
    output: str = Field(default="", max_length=1048576)
    redacted: bool = False
    output_truncated: bool = False
    error_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_failure_code(self) -> "RunnerTaskCompleteRequest":
        if self.status == "failed" and not self.error_code:
            raise ValueError("errorCode is required when task status is failed")
        return self


class RunnerTaskCompleteResponse(ApiModel):
    task: RunnerTaskResponse
    duplicate: bool
