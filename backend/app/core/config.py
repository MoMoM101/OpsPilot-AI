from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="OPSPILOT_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "OpsPilot Control Plane"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    docs_enabled: bool | None = None
    require_https: bool | None = None
    trust_forwarded_proto: bool = False
    database_url: str = Field(
        default="postgresql+asyncpg://opspilot:opspilot@localhost:5432/opspilot",
        repr=False,
    )
    database_password_file: Path | None = Field(default=None, repr=False)
    database_readiness_enabled: bool = True
    startup_recovery_enabled: bool | None = None
    startup_recovery_retry_seconds: float = Field(default=30, ge=1, le=3600)
    sse_poll_interval_seconds: float = Field(default=1.0, gt=0, le=30)
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0, le=120)
    sse_batch_size: int = Field(default=100, ge=1, le=1000)
    outbox_publisher_mode: Literal["disabled", "log", "webhook"] = "log"
    outbox_publisher_interval_seconds: float = Field(default=1, ge=0.1, le=60)
    outbox_publisher_batch_size: int = Field(default=100, ge=1, le=1000)
    outbox_max_publish_attempts: int = Field(default=10, ge=1, le=100)
    outbox_retry_base_seconds: float = Field(default=2, ge=0.1, le=3600)
    outbox_retry_max_seconds: float = Field(default=300, ge=1, le=86400)
    outbox_retention_days: int = Field(default=7, ge=1, le=3650)
    audit_retention_days: int = Field(default=365, ge=30, le=3650)
    audit_archive_batch_size: int = Field(default=10000, ge=1, le=100000)
    outbox_webhook_url: AnyHttpUrl | None = None
    outbox_webhook_token: str | None = Field(default=None, repr=False)
    outbox_webhook_token_file: Path | None = Field(default=None, repr=False)
    outbox_webhook_timeout_seconds: float = Field(default=10, ge=1, le=120)
    alert_correlation_window_seconds: int = Field(default=900, ge=60, le=86400)
    alertmanager_webhook_token: str | None = Field(default=None, repr=False)
    alertmanager_webhook_token_file: Path | None = Field(default=None, repr=False)
    runner_bootstrap_token: str | None = Field(default=None, repr=False)
    runner_bootstrap_token_file: Path | None = Field(default=None, repr=False)
    control_plane_auth_enabled: bool = True
    control_plane_bootstrap_token: str | None = Field(default=None, repr=False)
    control_plane_bootstrap_token_file: Path | None = Field(default=None, repr=False)
    principal_token_ttl_seconds: int = Field(default=2592000, ge=300, le=31536000)
    browser_session_cookie_name: str = "opspilot_session"
    browser_csrf_cookie_name: str = "opspilot_csrf"
    browser_session_ttl_seconds: int = Field(default=28800, ge=300, le=604800)
    browser_session_absolute_ttl_seconds: int = Field(default=604800, ge=3600, le=2592000)
    browser_cookie_secure: bool | None = None
    runner_lease_seconds: int = Field(default=60, ge=10, le=600)
    runner_task_lease_seconds: int = Field(default=120, ge=10, le=3600)
    resource_lock_lease_seconds: int = Field(default=120, ge=10, le=3600)
    action_execution_lease_seconds: int = Field(default=120, ge=10, le=3600)
    runner_task_max_output_bytes: int = Field(default=65536, ge=1024, le=1048576)
    runner_token_rotation_seconds: int = Field(default=86400, ge=60, le=2592000)
    runner_token_ttl_seconds: int = Field(default=604800, ge=300, le=7776000)
    runner_token_grace_seconds: int = Field(default=600, ge=30, le=86400)
    observability_monitor_interval_seconds: float = Field(default=15, ge=1, le=300)
    worker_health_stale_multiplier: float = Field(default=3, ge=2, le=10)
    worker_health_error_threshold: int = Field(default=3, ge=1, le=100)
    agent_runtime_enabled: bool = False
    agent_provider: Literal["openai", "lab_deterministic"] = "openai"
    agent_runtime_poll_interval_seconds: float = Field(default=2, ge=0.1, le=60)
    agent_runtime_lease_seconds: int = Field(default=60, ge=10, le=600)
    agent_runtime_no_progress_limit: int = Field(default=3, ge=1, le=20)
    agent_model_name: str | None = None
    agent_model_api_key: str | None = Field(default=None, repr=False)
    agent_model_base_url: str | None = None
    agent_model_request_limit: int = Field(default=2, ge=1, le=10)
    agent_model_input_tokens_limit: int = Field(default=16000, ge=1000, le=1000000)
    agent_model_output_tokens_limit: int = Field(default=4000, ge=100, le=100000)
    agent_model_check_timeout_seconds: float = Field(default=15, ge=1, le=120)
    agent_model_check_cooldown_seconds: float = Field(default=30, ge=1, le=3600)
    demo_data_enabled: bool = False
    lab_enabled: bool = False
    lab_controller_url: AnyHttpUrl | None = None
    lab_controller_token: str | None = Field(default=None, repr=False)
    lab_controller_timeout_seconds: float = Field(default=10, ge=1, le=60)
    cors_origins: list[AnyHttpUrl] = Field(
        default_factory=lambda: [AnyHttpUrl("http://localhost:5173")]
    )

    @model_validator(mode="after")
    def require_production_webhook_token(self) -> "Settings":
        if self.startup_recovery_enabled is None:
            self.startup_recovery_enabled = self.environment != "test"
        if self.docs_enabled is None:
            self.docs_enabled = self.environment != "production"
        if self.environment == "production" and self.docs_enabled:
            raise ValueError("API documentation cannot be enabled in production")
        if self.require_https is None:
            self.require_https = self.environment == "production"
        if self.browser_cookie_secure is None:
            self.browser_cookie_secure = self.environment == "production"
        if self.browser_session_ttl_seconds > self.browser_session_absolute_ttl_seconds:
            raise ValueError("Browser Session TTL cannot exceed its absolute TTL")
        if self.runner_token_rotation_seconds >= self.runner_token_ttl_seconds:
            raise ValueError("Runner token rotation must occur before token expiry")
        if self.runner_token_grace_seconds >= self.runner_token_ttl_seconds:
            raise ValueError("Runner token grace period must be shorter than token TTL")
        if self.database_password_file is not None:
            password = self._read_secret(self.database_password_file, "database password")
            self.database_url = (
                make_url(self.database_url)
                .set(password=password)
                .render_as_string(hide_password=False)
            )
        if self.alertmanager_webhook_token_file is not None:
            self.alertmanager_webhook_token = self._read_secret(
                self.alertmanager_webhook_token_file,
                "Alertmanager webhook token",
            )
        if self.runner_bootstrap_token_file is not None:
            self.runner_bootstrap_token = self._read_secret(
                self.runner_bootstrap_token_file,
                "Runner bootstrap token",
            )
        if self.control_plane_bootstrap_token_file is not None:
            self.control_plane_bootstrap_token = self._read_secret(
                self.control_plane_bootstrap_token_file,
                "control-plane bootstrap token",
            )
        if self.outbox_webhook_token_file is not None:
            self.outbox_webhook_token = self._read_secret(
                self.outbox_webhook_token_file,
                "Outbox webhook token",
            )
        if self.outbox_publisher_mode == "webhook" and self.outbox_webhook_url is None:
            raise ValueError("Outbox webhook URL is required in webhook publisher mode")
        if self.outbox_retry_base_seconds > self.outbox_retry_max_seconds:
            raise ValueError("Outbox retry base cannot exceed maximum delay")
        if self.environment == "production":
            if not self.alertmanager_webhook_token:
                raise ValueError("An Alertmanager webhook token is required in production")
            if not self.runner_bootstrap_token:
                raise ValueError("A Runner bootstrap token is required in production")
            if self.control_plane_auth_enabled and not self.control_plane_bootstrap_token:
                raise ValueError("A control-plane bootstrap token is required in production")
        if (
            self.agent_runtime_enabled
            and self.agent_provider == "openai"
            and (not self.agent_model_name or not self.agent_model_api_key)
        ):
            raise ValueError(
                "Agent model name and API key are required when Agent runtime is enabled"
            )
        if self.environment == "production" and self.lab_enabled:
            raise ValueError("Fault Lab cannot be enabled in production")
        if self.lab_enabled and (
            self.lab_controller_url is None or not self.lab_controller_token
        ):
            raise ValueError("Lab controller URL and token are required when Fault Lab is enabled")
        if self.agent_provider == "lab_deterministic" and not self.lab_enabled:
            raise ValueError("Deterministic Lab Agent provider requires Fault Lab to be enabled")
        return self

    @staticmethod
    def _read_secret(path: Path, name: str) -> str:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"Unable to read {name} file") from exc
        if not value or len(value.encode()) > 16384:
            raise ValueError(f"{name} file must contain 1 to 16384 bytes")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
