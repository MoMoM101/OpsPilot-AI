import json
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from opspilot_runner.contracts import ConnectorError, ExecutionResult, ReadOnlyConnector
from opspilot_runner.safety import redact, truncate_utf8
from opspilot_runner.target_policy import ProbeTargetPolicy, TargetPolicyError


class RagBusinessHealthError(ConnectorError):
    pass


class RagBusinessHealthConnector(ReadOnlyConnector):
    name = "rag"

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
        return ("rag.business_health",)

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult:
        url, question, expected_terms = self._validate(operation, parameters)
        started = time.perf_counter()
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=max(1, min(timeout_seconds, 300)),
                ) as client,
                client.stream("POST", url, json={"question": question}) as response,
            ):
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > 1048576:
                        raise RagBusinessHealthError(
                            "RAG_RESPONSE_TOO_LARGE", "RAG response exceeds 1 MiB"
                        )
                    content.extend(chunk)
                status_code = response.status_code
        except httpx.RequestError as exc:
            raise RagBusinessHealthError("RAG_UNAVAILABLE", type(exc).__name__) from exc
        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RagBusinessHealthError(
                "INVALID_RAG_RESPONSE", "RAG endpoint returned malformed JSON"
            ) from exc
        answer = raw.get("answer") if isinstance(raw, dict) else None
        if not isinstance(answer, str):
            answer = ""
        safe_answer, redacted = redact(answer)
        preview, preview_truncated = truncate_utf8(safe_answer, 2048)
        matched = [term for term in expected_terms if term.casefold() in answer.casefold()]
        healthy = (
            200 <= status_code < 300
            and bool(answer.strip())
            and len(matched) == len(expected_terms)
        )
        payload = {
            "reachable": True,
            "healthy": healthy,
            "statusCode": status_code,
            "latencyMs": round((time.perf_counter() - started) * 1000, 2),
            "answerPresent": bool(answer.strip()),
            "expectedTermCount": len(expected_terms),
            "matchedTermCount": len(matched),
            "answerPreview": preview,
        }
        output, output_truncated = truncate_utf8(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            self.max_output_bytes,
        )
        return ExecutionResult(
            summary=f"RAG business health={str(healthy).lower()} status={status_code}",
            output=output,
            redacted=redacted,
            truncated=preview_truncated or output_truncated,
        )

    def _validate(self, operation: str, parameters: dict[str, Any]) -> tuple[str, str, list[str]]:
        if operation != "rag.business_health":
            raise RagBusinessHealthError("UNSUPPORTED_RAG_OPERATION", "Unsupported RAG operation")
        if set(parameters) - {"url", "question", "expectedTerms"}:
            raise RagBusinessHealthError("INVALID_RAG_PARAMETERS", "Unsupported RAG parameters")
        url = parameters.get("url")
        question = parameters.get("question")
        terms = parameters.get("expectedTerms", [])
        if not isinstance(url, str) or not isinstance(question, str):
            raise RagBusinessHealthError(
                "INVALID_RAG_PARAMETERS", "RAG url and question are required"
            )
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise RagBusinessHealthError("UNSAFE_RAG_URL", "RAG URL is invalid or unsafe")
        try:
            self.policy.validate(
                parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
            )
        except (ValueError, TargetPolicyError) as exc:
            raise RagBusinessHealthError("RAG_TARGET_NOT_ALLOWED", str(exc)) from exc
        if not 1 <= len(question.strip()) <= 500:
            raise RagBusinessHealthError(
                "INVALID_RAG_QUESTION", "RAG question is outside safety bounds"
            )
        if (
            not isinstance(terms, list)
            or len(terms) > 20
            or any(not isinstance(term, str) or not 1 <= len(term.strip()) <= 100 for term in terms)
        ):
            raise RagBusinessHealthError(
                "INVALID_RAG_EXPECTATION", "RAG expected terms are outside safety bounds"
            )
        return url, question, terms
