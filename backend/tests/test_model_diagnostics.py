import asyncio
from typing import cast

from app.schemas.system import ModelConnectionCheckResponse
from app.services.agent_provider import (
    AgentProvider,
    AgentProviderError,
    ModelConnectionProbeOutput,
    ProviderResult,
)
from app.services.model_diagnostics import ModelDiagnosticService

SECRET = "sk-never-expose-this-model-secret"


class _SuccessProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def check_connection(self) -> ProviderResult[ModelConnectionProbeOutput]:
        self.calls += 1
        return ProviderResult(
            output=ModelConnectionProbeOutput(status="ok"),
            requests=1,
            input_tokens=1,
            output_tokens=1,
        )


class _ErrorProvider:
    async def check_connection(self) -> ProviderResult[ModelConnectionProbeOutput]:
        raise AgentProviderError(
            f"provider rejected credential {SECRET}",
            diagnostic_code="MODEL_AUTHENTICATION_FAILED",
        )


class _UnexpectedErrorProvider:
    async def check_connection(self) -> ProviderResult[ModelConnectionProbeOutput]:
        raise RuntimeError(f"base URL and key leaked: {SECRET}")


class _SlowProvider:
    async def check_connection(self) -> ProviderResult[ModelConnectionProbeOutput]:
        await asyncio.sleep(0.05)
        return ProviderResult(
            output=ModelConnectionProbeOutput(status="ok"),
            requests=1,
            input_tokens=1,
            output_tokens=1,
        )


class _DelayedSuccessProvider(_SuccessProvider):
    async def check_connection(self) -> ProviderResult[ModelConnectionProbeOutput]:
        await asyncio.sleep(0.01)
        return await super().check_connection()


def _service(
    provider: object,
    *,
    timeout: float = 1,
    cooldown: float = 30,
) -> ModelDiagnosticService:
    return ModelDiagnosticService(
        cast(AgentProvider, provider),
        provider_name="openai",
        runtime_enabled=True,
        timeout_seconds=timeout,
        cooldown_seconds=cooldown,
    )


def test_successful_model_check_is_cached_during_cooldown() -> None:
    provider = _SuccessProvider()
    service = _service(provider)

    first = asyncio.run(service.check())
    replay = asyncio.run(service.check())

    assert first.status == "ok"
    assert first.cached is False
    assert replay.status == "ok"
    assert replay.cached is True
    assert provider.calls == 1


def test_concurrent_model_checks_share_one_provider_request() -> None:
    provider = _DelayedSuccessProvider()
    service = _service(provider)

    async def run_checks() -> list[ModelConnectionCheckResponse]:
        return list(await asyncio.gather(service.check(), service.check()))

    results = asyncio.run(run_checks())

    assert provider.calls == 1
    assert [item.cached for item in results] == [False, True]


def test_provider_error_is_classified_without_exposing_original_message() -> None:
    result = asyncio.run(_service(_ErrorProvider()).check())

    assert result.status == "failed"
    assert result.error_code == "MODEL_AUTHENTICATION_FAILED"
    assert result.message == "Model provider rejected the configured credential"
    assert SECRET not in result.model_dump_json()


def test_unexpected_provider_error_is_reduced_to_safe_generic_diagnostic() -> None:
    result = asyncio.run(_service(_UnexpectedErrorProvider()).check())

    assert result.status == "failed"
    assert result.error_code == "MODEL_CHECK_FAILED"
    assert SECRET not in result.model_dump_json()


def test_model_check_has_an_independent_total_timeout() -> None:
    result = asyncio.run(_service(_SlowProvider(), timeout=0.01).check())

    assert result.status == "failed"
    assert result.error_code == "MODEL_TIMEOUT"
