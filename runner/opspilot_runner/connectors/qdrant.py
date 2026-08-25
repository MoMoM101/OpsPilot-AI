import json
import math
import re
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.safety import truncate_utf8
from opspilot_runner.target_policy import ProbeTargetPolicy, TargetPolicyError


class QdrantConnectorError(ConnectorError):
    pass


class QdrantConnector(ReadOnlyConnector):
    name = "qdrant"
    _operations = (
        "qdrant.health",
        "qdrant.collection",
        "qdrant.point_count",
        "qdrant.query_smoke",
    )

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
        return self._operations

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        url, body = self._validate(operation, parameters)
        payload = await self._request("GET" if body is None else "POST", url, body, timeout_seconds)
        normalized = self._normalize(operation, payload)
        output, truncated = truncate_utf8(
            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
            self.max_output_bytes,
        )
        return ExecutionResult(
            summary=self._summary(operation, normalized),
            output=output,
            redacted=False,
            truncated=truncated,
        )

    def _validate(
        self, operation: str, parameters: dict[str, Any]
    ) -> tuple[str, dict[str, Any] | None]:
        if operation not in self._operations:
            raise QdrantConnectorError(
                "UNSUPPORTED_QDRANT_OPERATION", "Unsupported Qdrant operation"
            )
        allowed = {"baseUrl"}
        if operation != "qdrant.health":
            allowed.add("collection")
        if operation == "qdrant.query_smoke":
            allowed.update({"vector", "limit"})
        if set(parameters) - allowed:
            raise QdrantConnectorError("INVALID_QDRANT_PARAMETERS", "Unsupported Qdrant parameters")
        base_url = parameters.get("baseUrl")
        if not isinstance(base_url, str):
            raise QdrantConnectorError("INVALID_QDRANT_URL", "Qdrant baseUrl is required")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise QdrantConnectorError(
                "INVALID_QDRANT_URL", "Only HTTP and HTTPS Qdrant URLs are supported"
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise QdrantConnectorError(
                "UNSAFE_QDRANT_URL", "Qdrant URL contains forbidden components"
            )
        try:
            self.policy.validate(
                parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
            )
        except (ValueError, TargetPolicyError) as exc:
            raise QdrantConnectorError("QDRANT_TARGET_NOT_ALLOWED", str(exc)) from exc
        path = parsed.path.rstrip("/")
        body: dict[str, Any] | None = None
        if operation == "qdrant.health":
            path += "/readyz"
        else:
            collection = parameters.get("collection")
            if not isinstance(collection, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{0,254}", collection
            ):
                raise QdrantConnectorError(
                    "INVALID_QDRANT_COLLECTION", "Qdrant collection name is invalid"
                )
            collection_path = quote(collection, safe="")
            if operation == "qdrant.collection":
                path += f"/collections/{collection_path}"
            elif operation == "qdrant.point_count":
                path += f"/collections/{collection_path}/points/count"
                body = {"exact": True}
            else:
                vector = parameters.get("vector")
                limit = parameters.get("limit", 3)
                if (
                    not isinstance(vector, list)
                    or not 1 <= len(vector) <= 4096
                    or any(
                        not isinstance(value, int | float)
                        or isinstance(value, bool)
                        or not math.isfinite(float(value))
                        for value in vector
                    )
                    or not isinstance(limit, int)
                    or isinstance(limit, bool)
                    or not 1 <= limit <= 20
                ):
                    raise QdrantConnectorError(
                        "INVALID_QDRANT_QUERY", "Qdrant smoke query is outside safety bounds"
                    )
                path += f"/collections/{collection_path}/points/query"
                body = {
                    "query": [float(value) for value in vector],
                    "limit": limit,
                    "with_payload": False,
                    "with_vector": False,
                }
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")), body

    async def _request(
        self, method: str, url: str, body: dict[str, Any] | None, timeout_seconds: int
    ) -> dict[str, Any]:
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=max(1, min(timeout_seconds, 300)),
                ) as client,
                client.stream(method, url, json=body) as response,
            ):
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > 1048576:
                        raise QdrantConnectorError(
                            "QDRANT_RESPONSE_TOO_LARGE", "Qdrant response exceeds 1 MiB"
                        )
                    content.extend(chunk)
        except httpx.RequestError as exc:
            raise QdrantConnectorError("QDRANT_UNAVAILABLE", type(exc).__name__) from exc
        if response.status_code != 200:
            raise QdrantConnectorError(
                "QDRANT_QUERY_FAILED", f"Qdrant returned HTTP {response.status_code}"
            )
        if not content:
            return {"status": "ok"}
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            text = content.decode(errors="replace").strip().lower()
            if text in {"ok", "healthz check passed", "readyz check passed"}:
                return {"status": "ok"}
            raise QdrantConnectorError(
                "INVALID_QDRANT_RESPONSE", "Qdrant returned malformed JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise QdrantConnectorError(
                "INVALID_QDRANT_RESPONSE", "Qdrant response must be an object"
            )
        return payload

    @staticmethod
    def _normalize(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result")
        if operation == "qdrant.health":
            return {"reachable": True, "ready": payload.get("status") == "ok"}
        if operation == "qdrant.point_count":
            count = result.get("count") if isinstance(result, dict) else None
            return {"reachable": True, "count": count if isinstance(count, int) else None}
        if operation == "qdrant.query_smoke":
            points = result.get("points", result) if isinstance(result, dict) else result
            count = len(points) if isinstance(points, list) else 0
            return {"reachable": True, "resultCount": min(count, 20)}
        config = result.get("config", {}) if isinstance(result, dict) else {}
        vectors = config.get("params", {}).get("vectors", {}) if isinstance(config, dict) else {}
        return {
            "reachable": True,
            "status": str(result.get("status", "unknown"))[:50]
            if isinstance(result, dict)
            else "unknown",
            "pointsCount": result.get("points_count") if isinstance(result, dict) else None,
            "vectors": len(vectors) if isinstance(vectors, dict) else 1,
        }

    @staticmethod
    def _summary(operation: str, payload: dict[str, Any]) -> str:
        if operation == "qdrant.health":
            return f"Qdrant ready={str(payload.get('ready') is True).lower()}"
        if operation == "qdrant.point_count":
            return f"Qdrant point count={payload.get('count')}"
        if operation == "qdrant.query_smoke":
            return f"Qdrant smoke query returned {payload.get('resultCount')} points"
        return f"Qdrant collection status={payload.get('status')}"
