import asyncio
from datetime import UTC, datetime
from time import monotonic

from app.schemas.system import ModelConnectionCheckResponse
from app.services.agent_provider import AgentProvider, AgentProviderError

_SAFE_ERROR_MESSAGES = {
    "MODEL_AUTHENTICATION_FAILED": "Model provider rejected the configured credential",
    "MODEL_RATE_LIMITED": "Model provider rate limit is active",
    "MODEL_TIMEOUT": "Model provider did not respond before the diagnostic timeout",
    "MODEL_UNAVAILABLE": "Model provider is temporarily unavailable",
    "MODEL_PROVIDER_ERROR": "Model provider rejected the connectivity check",
    "MODEL_CHECK_FAILED": "Model connectivity check failed",
}


class ModelDiagnosticService:
    def __init__(
        self,
        provider: AgentProvider | None,
        *,
        provider_name: str,
        runtime_enabled: bool,
        timeout_seconds: float,
        cooldown_seconds: float,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.runtime_enabled = runtime_enabled
        self.timeout_seconds = timeout_seconds
        self.cooldown_seconds = cooldown_seconds
        self._lock = asyncio.Lock()
        self._last_result: ModelConnectionCheckResponse | None = None
        self._last_completed_monotonic: float | None = None

    async def check(self) -> ModelConnectionCheckResponse:
        if not self.runtime_enabled:
            return self._static_result(
                status="disabled",
                message="Agent runtime is disabled",
            )
        if self.provider is None:
            return self._static_result(
                status="not_configured",
                message="Agent model provider is not configured",
            )
        async with self._lock:
            cached = self._cached_result()
            if cached is not None:
                return cached
            started = monotonic()
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    await self.provider.check_connection()
            except TimeoutError:
                result = self._failure("MODEL_TIMEOUT", started)
            except AgentProviderError as exc:
                code = (
                    exc.diagnostic_code
                    if exc.diagnostic_code in _SAFE_ERROR_MESSAGES
                    else "MODEL_PROVIDER_ERROR"
                )
                result = self._failure(code, started)
            except Exception:
                result = self._failure("MODEL_CHECK_FAILED", started)
            else:
                result = ModelConnectionCheckResponse(
                    status="ok",
                    provider=self.provider_name,
                    runtime_enabled=True,
                    connectivity_checked=True,
                    cached=False,
                    latency_ms=max(0, round((monotonic() - started) * 1000)),
                    error_code=None,
                    message="Model provider connectivity check succeeded",
                    checked_at=datetime.now(UTC),
                )
            self._last_result = result
            self._last_completed_monotonic = monotonic()
            return result

    def _cached_result(self) -> ModelConnectionCheckResponse | None:
        if self._last_result is None or self._last_completed_monotonic is None:
            return None
        if monotonic() - self._last_completed_monotonic >= self.cooldown_seconds:
            return None
        return self._last_result.model_copy(update={"cached": True})

    def _failure(self, code: str, started: float) -> ModelConnectionCheckResponse:
        return ModelConnectionCheckResponse(
            status="failed",
            provider=self.provider_name,
            runtime_enabled=True,
            connectivity_checked=True,
            cached=False,
            latency_ms=max(0, round((monotonic() - started) * 1000)),
            error_code=code,
            message=_SAFE_ERROR_MESSAGES[code],
            checked_at=datetime.now(UTC),
        )

    def _static_result(self, *, status: str, message: str) -> ModelConnectionCheckResponse:
        return ModelConnectionCheckResponse(
            status=status,
            provider=self.provider_name,
            runtime_enabled=self.runtime_enabled,
            connectivity_checked=False,
            cached=False,
            latency_ms=None,
            error_code=None,
            message=message,
            checked_at=datetime.now(UTC),
        )
