import json
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.safety import redact, truncate_utf8
from opspilot_runner.target_policy import ProbeTargetPolicy, TargetPolicyError


class PrometheusConnectorError(ConnectorError):
    pass


class PrometheusConnector(ReadOnlyConnector):
    name = "prometheus"

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
        return ("prometheus.query", "prometheus.query_range")

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        url, query_parameters = self._validate(operation, parameters)
        raw = await self._request(url, query_parameters, timeout_seconds)
        normalized, truncated = self._normalize(raw)
        output = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        safe_output, redacted = redact(output)
        bounded, byte_truncated = truncate_utf8(safe_output, self.max_output_bytes)
        result_count = len(normalized.get("data", {}).get("result", []))
        return ExecutionResult(
            summary=f"Prometheus query returned {result_count} normalized series",
            output=bounded,
            redacted=redacted,
            truncated=truncated or byte_truncated,
        )

    def _validate(
        self,
        operation: str,
        parameters: dict[str, Any],
    ) -> tuple[str, dict[str, str]]:
        if operation not in self.observe_operations:
            raise PrometheusConnectorError(
                "UNSUPPORTED_PROMETHEUS_OPERATION",
                "Unsupported Prometheus operation",
            )
        common = {"baseUrl", "query"}
        allowed = (
            common | {"time"}
            if operation == "prometheus.query"
            else common | {"start", "end", "stepSeconds"}
        )
        if set(parameters) - allowed:
            raise PrometheusConnectorError(
                "INVALID_PROMETHEUS_PARAMETERS",
                "Unsupported Prometheus parameters",
            )
        base_url = parameters.get("baseUrl")
        query = parameters.get("query")
        if not isinstance(base_url, str) or not isinstance(query, str):
            raise PrometheusConnectorError(
                "INVALID_PROMETHEUS_PARAMETERS",
                "baseUrl and query are required",
            )
        if not query.strip() or len(query) > 2000:
            raise PrometheusConnectorError(
                "INVALID_PROMQL",
                "PromQL must contain between 1 and 2000 characters",
            )
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise PrometheusConnectorError(
                "INVALID_PROMETHEUS_URL",
                "Only HTTP and HTTPS Prometheus URLs are supported",
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PrometheusConnectorError(
                "UNSAFE_PROMETHEUS_URL",
                "Prometheus URL credentials, query strings, and fragments are forbidden",
            )
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            self.policy.validate(parsed.hostname, port)
        except (ValueError, TargetPolicyError) as exc:
            raise PrometheusConnectorError("PROMETHEUS_TARGET_NOT_ALLOWED", str(exc)) from exc
        endpoint = "query" if operation == "prometheus.query" else "query_range"
        path = parsed.path.rstrip("/") + f"/api/v1/{endpoint}"
        url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        request_parameters = {"query": query}
        if operation == "prometheus.query":
            if "time" in parameters:
                request_parameters["time"] = self._timestamp(parameters["time"], "time")
        else:
            start = self._timestamp(parameters.get("start"), "start")
            end = self._timestamp(parameters.get("end"), "end")
            start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
            step = parameters.get("stepSeconds", 60)
            if (
                not isinstance(step, int)
                or isinstance(step, bool)
                or not 1 <= step <= 3600
                or end_time <= start_time
                or (end_time - start_time).total_seconds() > 21600
                or (end_time - start_time).total_seconds() / step > 11000
            ):
                raise PrometheusConnectorError(
                    "INVALID_PROMETHEUS_RANGE",
                    "Prometheus range or step exceeds safety limits",
                )
            request_parameters.update({"start": start, "end": end, "step": str(step)})
        return url, request_parameters

    async def _request(
        self,
        url: str,
        parameters: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        limit = 1048576
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=max(1, min(timeout_seconds, 300)),
                ) as client,
                client.stream("GET", url, params=parameters) as response,
            ):
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > limit:
                        raise PrometheusConnectorError(
                            "PROMETHEUS_RESPONSE_TOO_LARGE",
                            "Prometheus response exceeds 1 MiB",
                        )
                    content.extend(chunk)
        except httpx.RequestError as exc:
            raise PrometheusConnectorError(
                "PROMETHEUS_UNAVAILABLE",
                type(exc).__name__,
            ) from exc
        if response.status_code != 200:
            raise PrometheusConnectorError(
                "PROMETHEUS_QUERY_FAILED",
                f"Prometheus returned HTTP {response.status_code}",
            )
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PrometheusConnectorError(
                "INVALID_PROMETHEUS_RESPONSE",
                "Prometheus returned malformed JSON",
            ) from exc
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise PrometheusConnectorError(
                "PROMETHEUS_QUERY_FAILED",
                "Prometheus query status was not successful",
            )
        return payload

    def _normalize(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise PrometheusConnectorError(
                "INVALID_PROMETHEUS_RESPONSE",
                "Prometheus response has no data object",
            )
        raw_result = data.get("result", [])
        if not isinstance(raw_result, list):
            raise PrometheusConnectorError(
                "INVALID_PROMETHEUS_RESPONSE",
                "Prometheus result is not a list",
            )
        truncated = len(raw_result) > 100
        result = [
            self._normalize_series(item) for item in raw_result[:100] if isinstance(item, dict)
        ]
        if any(
            item.get("samplesTruncated") is True or item.get("labelsTruncated") is True
            for item in result
        ):
            truncated = True
        normalized = {
            "status": "success",
            "data": {
                "resultType": str(data.get("resultType", "unknown"))[:50],
                "result": result,
            },
            "seriesTruncated": truncated,
        }
        while (
            result
            and len(json.dumps(normalized, ensure_ascii=False).encode()) > self.max_output_bytes
        ):
            result.pop()
            normalized["seriesTruncated"] = True
            truncated = True
        return normalized, truncated

    @staticmethod
    def _normalize_series(item: dict[str, Any]) -> dict[str, Any]:
        metric = item.get("metric", {})
        safe_metric = (
            {str(key)[:100]: str(value)[:200] for key, value in list(metric.items())[:50]}
            if isinstance(metric, dict)
            else {}
        )
        result: dict[str, Any] = {
            "metric": safe_metric,
            "labelsTruncated": isinstance(metric, dict) and len(metric) > 50,
        }
        value = item.get("value")
        if isinstance(value, list) and len(value) == 2:
            result["value"] = [value[0], str(value[1])[:100]]
        values = item.get("values")
        if isinstance(values, list):
            result["values"] = [
                [sample[0], str(sample[1])[:100]]
                for sample in values[:500]
                if isinstance(sample, list) and len(sample) == 2
            ]
            result["samplesTruncated"] = len(values) > 500
        return result

    @staticmethod
    def _timestamp(value: Any, name: str) -> str:
        if not isinstance(value, str):
            raise PrometheusConnectorError(
                "INVALID_PROMETHEUS_TIMESTAMP",
                f"{name} must be an RFC3339 timestamp",
            )
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PrometheusConnectorError(
                "INVALID_PROMETHEUS_TIMESTAMP",
                f"{name} must be an RFC3339 timestamp",
            ) from exc
        if parsed.tzinfo is None:
            raise PrometheusConnectorError(
                "INVALID_PROMETHEUS_TIMESTAMP",
                f"{name} must include a timezone",
            )
        return value
