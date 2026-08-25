import socket
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="OPSPILOT_RUNNER_",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    control_plane_url: str = "http://localhost:8000/runner/v1"
    environment: Literal["development", "staging", "production"] = "development"
    allow_insecure_http: bool = False
    name: str = Field(default_factory=socket.gethostname, min_length=1, max_length=150)
    environment_id: UUID | None = None
    bootstrap_token: str | None = Field(default=None, repr=False)
    bootstrap_token_file: Path | None = Field(default=None, repr=False)
    credential_file: Path = Path(".opspilot-runner-credentials.json")
    heartbeat_seconds: float = Field(default=20, ge=5, le=300)
    task_renew_seconds: float = Field(default=30, ge=1, le=300)
    action_renew_seconds: float = Field(default=30, ge=1, le=300)
    action_timeout_seconds: int = Field(default=120, ge=1, le=900)
    poll_seconds: float = Field(default=2, ge=0.2, le=60)
    docker_timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_output_bytes: int = Field(default=65536, ge=1024, le=1048576)
    connector_circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    connector_circuit_recovery_seconds: float = Field(default=30, ge=1, le=3600)
    connector_retry_max_attempts: int = Field(default=2, ge=1, le=5)
    connector_retry_base_seconds: float = Field(default=0.2, ge=0.01, le=30)
    connector_retry_max_seconds: float = Field(default=2, ge=0.01, le=60)
    connector_retry_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    log_allowed_roots: list[Path] = Field(default_factory=list)
    journal_allowed_units: list[str] = Field(default_factory=list)
    probe_allowed_hosts: list[str] = Field(default_factory=list)
    probe_allowed_ports: list[int] = Field(default_factory=list)
    sqlite_allowed_roots: list[Path] = Field(default_factory=list)

    @model_validator(mode="after")
    def load_bootstrap_token_file(self) -> "RunnerSettings":
        control_plane = urlsplit(self.control_plane_url)
        if control_plane.scheme not in {"http", "https"} or not control_plane.netloc:
            raise ValueError("Runner control-plane URL must use HTTP or HTTPS")
        if (
            self.environment == "production"
            and control_plane.scheme != "https"
            and not self.allow_insecure_http
        ):
            raise ValueError("Production Runner control-plane URL must use HTTPS")
        if self.connector_retry_base_seconds > self.connector_retry_max_seconds:
            raise ValueError("Connector retry base delay cannot exceed maximum delay")
        if self.bootstrap_token_file is None:
            return self
        try:
            value = self.bootstrap_token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError("Unable to read Runner bootstrap token file") from exc
        if not value or len(value.encode()) > 16384:
            raise ValueError("Runner bootstrap token file must contain 1 to 16384 bytes")
        self.bootstrap_token = value
        return self
