from pathlib import Path

import pytest
from pydantic import ValidationError

from opspilot_runner.config import RunnerSettings


def test_runner_loads_bootstrap_token_file(tmp_path: Path) -> None:
    secret = tmp_path / "runner-token"
    secret.write_text("runner-secret\n", encoding="utf-8")

    settings = RunnerSettings(bootstrap_token_file=secret)

    assert settings.bootstrap_token == "runner-secret"


def test_runner_rejects_empty_bootstrap_token_file(tmp_path: Path) -> None:
    secret = tmp_path / "runner-token"
    secret.write_text("", encoding="utf-8")

    with pytest.raises(ValidationError, match="must contain 1 to 16384 bytes"):
        RunnerSettings(bootstrap_token_file=secret)


def test_production_runner_requires_https() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        RunnerSettings(
            environment="production",
            control_plane_url="http://control-plane.internal/runner/v1",
        )

    settings = RunnerSettings(
        environment="production",
        control_plane_url="http://backend:8000/runner/v1",
        allow_insecure_http=True,
    )
    assert settings.allow_insecure_http is True


def test_connector_circuit_breaker_configuration_is_bounded() -> None:
    with pytest.raises(ValidationError):
        RunnerSettings(connector_circuit_failure_threshold=0)
    with pytest.raises(ValidationError):
        RunnerSettings(connector_circuit_recovery_seconds=0)

    settings = RunnerSettings(
        connector_circuit_failure_threshold=3,
        connector_circuit_recovery_seconds=15,
    )
    assert settings.connector_circuit_failure_threshold == 3
    assert settings.connector_circuit_recovery_seconds == 15


def test_connector_retry_configuration_is_bounded_and_ordered() -> None:
    with pytest.raises(ValidationError):
        RunnerSettings(connector_retry_max_attempts=0)
    with pytest.raises(ValidationError, match="cannot exceed"):
        RunnerSettings(
            connector_retry_base_seconds=2,
            connector_retry_max_seconds=1,
        )
    with pytest.raises(ValidationError):
        RunnerSettings(connector_retry_jitter_ratio=1.1)

    settings = RunnerSettings(
        connector_retry_max_attempts=3,
        connector_retry_base_seconds=0.5,
        connector_retry_max_seconds=4,
        connector_retry_jitter_ratio=0.1,
    )
    assert settings.connector_retry_max_attempts == 3
    assert settings.connector_retry_base_seconds == 0.5
    assert settings.connector_retry_max_seconds == 4
    assert settings.connector_retry_jitter_ratio == 0.1
