import json
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.safety import redact, truncate_utf8
from opspilot_runner.target_policy import ProbeTargetPolicy, TargetPolicyError


class HttpProbeError(ConnectorError):
    pass


class HttpProbeConnector(ReadOnlyConnector):
    name = "http"

    def __init__(
        self,
        policy: ProbeTargetPolicy,
        *,
        max_output_bytes: int = 65536,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.policy = policy
        self.max_output_bytes = max_output_bytes
        self.transport = transport

    @property
    def observe_operations(self) -> tuple[str, ...]:
        return ("http.probe",)

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        url, method, expected, capture_body = self._validate(operation, parameters)
        started = time.perf_counter()
        payload: dict[str, Any]
        redacted = False
        truncated = False
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=max(1, min(timeout_seconds, 300)),
                ) as client,
                client.stream(method, url) as response,
            ):
                payload = {
                    "reachable": True,
                    "statusCode": response.status_code,
                    "healthy": response.status_code in expected,
                    "latencyMs": round((time.perf_counter() - started) * 1000, 2),
                    "contentType": response.headers.get("content-type"),
                    "redirectLocationPresent": "location" in response.headers,
                }
                if capture_body and method != "HEAD":
                    content, stream_truncated = await self._bounded_body(response)
                    safe_content, redacted = redact(content.decode(errors="replace"))
                    body, body_truncated = truncate_utf8(safe_content, 4096)
                    payload["bodyPreview"] = body
                    truncated = stream_truncated or body_truncated
        except httpx.RequestError as exc:
            payload = {
                "reachable": False,
                "healthy": False,
                "latencyMs": round((time.perf_counter() - started) * 1000, 2),
                "errorType": type(exc).__name__,
            }
        output, output_truncated = truncate_utf8(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            self.max_output_bytes,
        )
        healthy = payload.get("healthy") is True
        status = payload.get("statusCode", "unreachable")
        return ExecutionResult(
            summary=f"HTTP probe status={status} healthy={str(healthy).lower()}",
            output=output,
            redacted=redacted,
            truncated=truncated or output_truncated,
        )

    def _validate(
        self,
        operation: str,
        parameters: dict[str, Any],
    ) -> tuple[str, str, frozenset[int], bool]:
        if operation != "http.probe":
            raise HttpProbeError("UNSUPPORTED_HTTP_OPERATION", "Unsupported HTTP operation")
        unexpected = set(parameters) - {
            "url",
            "method",
            "expectedStatuses",
            "captureBody",
        }
        if unexpected:
            raise HttpProbeError("INVALID_HTTP_PARAMETERS", "Unsupported HTTP parameters")
        raw_url = parameters.get("url")
        if not isinstance(raw_url, str):
            raise HttpProbeError("INVALID_HTTP_URL", "HTTP probe URL is required")
        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HttpProbeError("INVALID_HTTP_URL", "Only HTTP and HTTPS URLs are supported")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise HttpProbeError(
                "UNSAFE_HTTP_URL",
                "URL credentials, fragments, and query strings are not allowed",
            )
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            self.policy.validate(parsed.hostname, port)
        except (ValueError, TargetPolicyError) as exc:
            raise HttpProbeError("HTTP_TARGET_NOT_ALLOWED", str(exc)) from exc
        method = parameters.get("method", "GET")
        if method not in {"GET", "HEAD"}:
            raise HttpProbeError("INVALID_HTTP_METHOD", "Only GET and HEAD are supported")
        statuses = parameters.get("expectedStatuses", [200])
        if not isinstance(statuses, list) or not statuses:
            raise HttpProbeError("INVALID_HTTP_PARAMETERS", "Expected statuses are required")
        expected = frozenset(statuses)
        if any(not isinstance(item, int) or not 100 <= item <= 599 for item in expected):
            raise HttpProbeError("INVALID_HTTP_PARAMETERS", "Invalid expected HTTP status")
        capture_body = parameters.get("captureBody", False)
        if not isinstance(capture_body, bool):
            raise HttpProbeError("INVALID_HTTP_PARAMETERS", "captureBody must be boolean")
        return raw_url, method, expected, capture_body

    @staticmethod
    async def _bounded_body(response: httpx.Response) -> tuple[bytes, bool]:
        limit = 4096
        result = bytearray()
        async for chunk in response.aiter_bytes():
            remaining = limit + 1 - len(result)
            if remaining <= 0:
                break
            result.extend(chunk[:remaining])
        return bytes(result[:limit]), len(result) > limit
