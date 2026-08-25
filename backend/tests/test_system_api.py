from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings


def test_health_returns_service_metadata_and_correlation_headers() -> None:
    app = create_app(Settings(environment="test", database_readiness_enabled=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "OpsPilot Control Plane",
        "version": "0.1.0",
    }
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Trace-ID"]


def test_ready_is_ready_without_registered_external_probes() -> None:
    app = create_app(Settings(environment="test", database_readiness_enabled=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}


def test_worker_health_reports_disabled_workers_without_changing_user_openapi() -> None:
    app = create_app(Settings(environment="test", database_readiness_enabled=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/worker-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["workers"]["observability_monitor"]["enabled"] is False
    assert payload["workers"]["agent_runtime"]["enabled"] is False
    assert "/api/v1/worker-health" not in app.openapi()["paths"]


def test_control_plane_mode_is_public_and_normal_when_recovery_is_disabled() -> None:
    app = create_app(Settings(environment="test", database_readiness_enabled=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/system/mode")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "normal",
        "reasonCode": None,
        "recoveryEnabled": False,
        "recoveryAttempts": 0,
        "lastRecoveryAttemptAt": None,
        "lastRecoveredAt": None,
        "lastRecoveryResult": {},
    }


def test_read_only_mode_blocks_control_plane_writes_but_keeps_reads_available() -> None:
    app = create_app(Settings(environment="test", database_readiness_enabled=False))
    app.state.control_plane_mode.mode = "read_only"
    app.state.control_plane_mode.reason_code = "STARTUP_RECOVERY_FAILED"

    with TestClient(app) as client:
        read_response = client.get("/api/v1/system/mode")
        write_response = client.post(
            "/api/v1/environments",
            json={"name": "blocked", "slug": "blocked"},
        )
        runner_claim = client.post(
            "/runner/v1/runners/00000000-0000-0000-0000-000000000001/actions/claim",
            json={"accessToken": "secret", "runnerFencingToken": 1},
        )
        model_diagnostic = client.post("/api/v1/system/model-connection-check")

    assert read_response.status_code == 200
    assert read_response.json()["mode"] == "read_only"
    assert write_response.status_code == 503
    assert write_response.headers["Retry-After"] == "30"
    error = write_response.json()["error"]
    assert error["code"] == "CONTROL_PLANE_READ_ONLY"
    assert error["details"] == {"reasonCode": "STARTUP_RECOVERY_FAILED"}
    assert error["request_id"] == write_response.headers["X-Request-ID"]
    assert runner_claim.status_code == 503
    assert runner_claim.json()["error"]["code"] == "CONTROL_PLANE_READ_ONLY"
    assert model_diagnostic.status_code == 200
    assert model_diagnostic.json()["status"] == "disabled"


def test_admin_recovery_endpoint_can_restore_writable_mode() -> None:
    app = create_app(Settings(environment="test", database_readiness_enabled=False))
    app.state.control_plane_mode.recovery_enabled = True
    app.state.control_plane_mode.mode = "read_only"
    app.state.control_plane_mode.reason_code = "STARTUP_RECOVERY_FAILED"

    async def recovered() -> dict[str, int]:
        return {"staleRunners": 0, "unknownActions": 0, "unknownCompensations": 0}

    app.state.control_plane_recovery.scan = recovered
    with TestClient(app) as client:
        response = client.post("/api/v1/system/recovery")

    assert response.status_code == 200
    assert response.json()["mode"] == "normal"
    assert response.json()["recoveryAttempts"] == 1


def test_failed_startup_recovery_keeps_service_read_only_and_not_ready() -> None:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=True,
            startup_recovery_enabled=True,
            startup_recovery_retry_seconds=3600,
        )
    )

    with TestClient(app) as client:
        mode = client.get("/api/v1/system/mode")
        readiness = client.get("/api/v1/ready")

    assert mode.status_code == 200
    assert mode.json()["mode"] == "read_only"
    assert mode.json()["reasonCode"] == "STARTUP_RECOVERY_FAILED"
    assert readiness.status_code == 503
    assert readiness.json()["checks"]["control_plane_recovery"] is False


def test_not_found_uses_normalized_error_contract() -> None:
    app = create_app(Settings(environment="test", database_readiness_enabled=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "HTTP_404"
    assert error["message"] == "Not Found"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert error["trace_id"] == response.headers["X-Trace-ID"]


def test_failed_readiness_probe_returns_service_unavailable() -> None:
    app = create_app(Settings(environment="test", database_readiness_enabled=False))

    async def failed_probe() -> bool:
        raise RuntimeError("database is unavailable")

    app.state.readiness.register("database", failed_probe)

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": False}}


def test_user_openapi_excludes_runner_and_internal_write_planes() -> None:
    app = create_app(Settings(environment="test", database_readiness_enabled=False))

    schema = app.openapi()
    paths = schema["paths"]

    checkpoint_path = paths["/api/v1/investigation-runs/{run_id}/checkpoints"]
    assert set(checkpoint_path) == {"get"}
    assert "/api/v1/investigation-runs/{run_id}/transitions" not in paths
    assert not any(path.startswith("/runner/v1") for path in paths)
    assert not any(path.startswith("/internal/v1") for path in paths)
    assert "/api/v1/actions/{action_id}/lock" not in paths
    assert "/api/v1/actions/{action_id}/lock/renew" not in paths
    assert "/api/v1/actions/{action_id}/lock/release" not in paths

    action_execution = schema["components"]["schemas"]["ActionExecutionResponse"]
    compensation_execution = schema["components"]["schemas"]["CompensationExecutionResponse"]
    sensitive_fields = {
        "runnerId",
        "runnerFencingToken",
        "executionFencingToken",
        "resourceFencingToken",
    }
    assert sensitive_fields.isdisjoint(action_execution["properties"])
    assert sensitive_fields.isdisjoint(compensation_execution["properties"])
    resource_lock = schema["components"]["schemas"]["ResourceLockResponse"]
    assert "fencingToken" not in resource_lock["properties"]
    compensation_dispatch = schema["components"]["schemas"]["CompensationDispatch"]
    assert set(compensation_dispatch["properties"]) == {"expectedVersion"}


def test_https_enforcement_allows_health_and_trusted_forwarding() -> None:
    app = create_app(
        Settings(
            environment="test",
            database_readiness_enabled=False,
            require_https=True,
            trust_forwarded_proto=True,
        )
    )

    with TestClient(app, base_url="http://testserver") as client:
        health = client.get("/api/v1/health")
        rejected = client.get("/api/v1/does-not-exist")
        forwarded = client.get(
            "/api/v1/does-not-exist",
            headers={"X-Forwarded-Proto": "https"},
        )

    assert health.status_code == 200
    assert rejected.status_code == 426
    assert rejected.json()["error"]["code"] == "HTTPS_REQUIRED"
    assert forwarded.status_code == 404
