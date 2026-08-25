from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings


def _secret(tmp_path: Path, name: str, value: str) -> Path:
    path = tmp_path / name
    path.write_text(value, encoding="utf-8")
    return path


def test_production_settings_load_file_secrets(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://opspilot@postgres:5432/opspilot",
        database_password_file=_secret(tmp_path, "database", "db p@ss"),
        alertmanager_webhook_token_file=_secret(tmp_path, "alertmanager", "alert-secret"),
        runner_bootstrap_token_file=_secret(tmp_path, "runner", "runner-secret"),
        control_plane_bootstrap_token_file=_secret(tmp_path, "control", "control-secret"),
    )

    assert make_url(settings.database_url).password == "db p@ss"
    assert settings.alertmanager_webhook_token == "alert-secret"
    assert settings.runner_bootstrap_token == "runner-secret"
    assert settings.control_plane_bootstrap_token == "control-secret"


def test_empty_secret_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="must contain 1 to 16384 bytes"):
        Settings(database_password_file=_secret(tmp_path, "empty", "\n"))


def test_production_security_defaults_disable_docs_and_require_https(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        alertmanager_webhook_token_file=_secret(tmp_path, "alert", "alert-secret"),
        runner_bootstrap_token_file=_secret(tmp_path, "runner", "runner-secret"),
        control_plane_bootstrap_token_file=_secret(tmp_path, "control", "control-secret"),
    )

    assert settings.docs_enabled is False
    assert settings.require_https is True

    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        Settings(
            environment="production",
            docs_enabled=True,
            alertmanager_webhook_token="alert-secret",
            runner_bootstrap_token="runner-secret",
            control_plane_bootstrap_token="control-secret",
        )


def test_deterministic_agent_provider_is_restricted_to_fault_lab() -> None:
    with pytest.raises(ValidationError, match="requires Fault Lab"):
        Settings(agent_runtime_enabled=True, agent_provider="lab_deterministic")

    settings = Settings(
        environment="test",
        agent_runtime_enabled=True,
        agent_provider="lab_deterministic",
        lab_enabled=True,
        lab_controller_url="http://lab-controller:8010",
        lab_controller_token="lab-token",
    )
    assert settings.agent_model_name is None
    assert settings.agent_model_api_key is None
