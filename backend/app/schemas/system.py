from datetime import datetime
from typing import Literal

from app.schemas.base import ApiModel


class HealthResponse(ApiModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(ApiModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]


class WorkerStatusResponse(ApiModel):
    enabled: bool
    healthy: bool
    task_running: bool
    started_at: datetime | None
    last_heartbeat_at: datetime | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    consecutive_errors: int
    total_errors: int
    last_error_type: str | None
    stale_after_seconds: float


class WorkerHealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    workers: dict[str, WorkerStatusResponse]


class ControlPlaneModeResponse(ApiModel):
    mode: Literal["recovering", "normal", "read_only"]
    reason_code: str | None
    recovery_enabled: bool
    recovery_attempts: int
    last_recovery_attempt_at: datetime | None
    last_recovered_at: datetime | None
    last_recovery_result: dict[str, int]


class SetupStatusResponse(ApiModel):
    status: Literal["initialization_required", "ready"]
    service: str
    version: str
    authentication_enabled: bool
    initial_admin_created: bool
    bootstrap_available: bool


class DeploymentPreflightCheckResponse(ApiModel):
    key: str
    status: Literal["pass", "action_required", "warning"]
    blocking: bool
    message: str


class DeploymentPreflightResponse(ApiModel):
    status: Literal["ready", "action_required"]
    checked_at: datetime
    checks: list[DeploymentPreflightCheckResponse]


class ModelConnectionCheckResponse(ApiModel):
    status: Literal["ok", "failed", "disabled", "not_configured"]
    provider: Literal["openai", "lab_deterministic"]
    runtime_enabled: bool
    connectivity_checked: bool
    cached: bool
    latency_ms: int | None
    error_code: Literal[
        "MODEL_AUTHENTICATION_FAILED",
        "MODEL_RATE_LIMITED",
        "MODEL_TIMEOUT",
        "MODEL_UNAVAILABLE",
        "MODEL_PROVIDER_ERROR",
        "MODEL_CHECK_FAILED",
    ] | None
    message: str
    checked_at: datetime
