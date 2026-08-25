import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.application import create_app
from app.core.config import Settings
from app.services.observability import ObservabilityService
from app.services.runner_tasks import RunnerTaskService
from app.storage import Base
from app.storage.models import RunnerLeaseRecord, RunnerRecord


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
            runner_lease_seconds=60,
            runner_task_lease_seconds=60,
            runner_task_max_output_bytes=1024,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(app) as test_client:
        yield test_client


def _setup(client: TestClient) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "Runner task test", "slug": "runner-task-test"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "docker-host-01",
            "kind": "docker-host",
        },
    ).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Container health degraded",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    runner = client.post(
        "/runner/v1/runners/register",
        json={
            "name": "docker-read-runner-01",
            "softwareVersion": "0.1.0",
            "environmentId": environment["id"],
            "capabilities": [
                {
                    "connector": "docker",
                    "contractVersion": "1.0",
                    "observe": [
                        "docker.list_containers",
                        "docker.inspect_container",
                        "docker.container_logs",
                        "docker.container_health",
                    ],
                }
            ],
        },
    ).json()
    return resource, incident, runner


def _move_to_investigating(client: TestClient, incident: dict[str, object]) -> dict[str, object]:
    for target in ("CORRELATING", "INVESTIGATING"):
        incident = client.post(
            f"/api/v1/incidents/{incident['id']}/transitions",
            json={"target": target, "expectedVersion": incident["version"]},
        ).json()
    return incident


def test_runner_task_claim_renew_complete_and_idempotency(client: TestClient) -> None:
    resource, incident, runner = _setup(client)
    task_payload = {
        "incidentId": incident["id"],
        "resourceId": resource["id"],
        "runnerId": runner["id"],
        "connector": "docker",
        "operation": "docker.container_logs",
        "parameters": {"containerId": "api-01", "tail": 200},
        "idempotencyKey": "incident-container-logs-001",
        "timeoutSeconds": 30,
    }
    created_response = client.post("/api/v1/runner-tasks", json=task_payload)
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["status"] == "queued"

    duplicate = client.post("/api/v1/runner-tasks", json=task_payload).json()
    assert duplicate["id"] == created["id"]

    authorization = {"Authorization": f"Bearer {runner['accessToken']}"}
    claim_response = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/claim",
        json={"runnerFencingToken": runner["fencingToken"]},
        headers=authorization,
    )
    assert claim_response.status_code == 200
    claimed = claim_response.json()["task"]
    assert claimed["id"] == created["id"]
    assert claimed["attempt"] == 1

    renew_response = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/{created['id']}/renew",
        json={"taskFencingToken": claimed["taskFencingToken"]},
        headers=authorization,
    )
    assert renew_response.status_code == 200
    assert renew_response.json()["status"] == "leased"

    completion_id = str(uuid4())
    completion_payload = {
        "completionId": completion_id,
        "taskFencingToken": claimed["taskFencingToken"],
        "status": "succeeded",
        "summary": "Collected bounded container logs",
        "output": "token=must-not-be-stored " + ("x" * 2000),
    }
    complete_response = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/{created['id']}/complete",
        json=completion_payload,
        headers=authorization,
    )
    assert complete_response.status_code == 200
    completed = complete_response.json()
    assert completed["duplicate"] is False
    assert completed["task"]["status"] == "succeeded"
    assert completed["task"]["outputTruncated"] is True
    assert completed["task"]["evidenceId"] is not None

    duplicate_complete = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/{created['id']}/complete",
        json=completion_payload,
        headers=authorization,
    ).json()
    assert duplicate_complete["duplicate"] is True
    assert duplicate_complete["task"]["evidenceId"] == completed["task"]["evidenceId"]

    evidence_response = client.get(f"/api/v1/evidence/{completed['task']['evidenceId']}")
    assert evidence_response.status_code == 200
    evidence = evidence_response.json()
    assert evidence["incidentId"] == incident["id"]
    assert evidence["resourceId"] == resource["id"]
    assert evidence["collectionStatus"] == "succeeded"
    assert evidence["timeConfidence"] == "runner_reported"
    assert evidence["redacted"] is True
    assert evidence["data"]["outputTruncated"] is True
    assert "must-not-be-stored" not in evidence["data"]["content"]

    incident_evidence = client.get(
        f"/api/v1/incidents/{incident['id']}/evidence",
        params={"resource_id": resource["id"], "evidence_type": "runner_observation"},
    )
    assert incident_evidence.status_code == 200
    assert incident_evidence.headers["X-Total-Count"] == "1"
    assert incident_evidence.headers["X-Limit"] == "50"
    assert incident_evidence.headers["X-Offset"] == "0"
    assert [item["id"] for item in incident_evidence.json()] == [evidence["id"]]

    listed_response = client.get(
        "/api/v1/runner-tasks",
        params={"status": "succeeded", "incident_id": incident["id"]},
    )
    assert listed_response.headers["X-Total-Count"] == "1"
    assert listed_response.headers["X-Limit"] == "50"
    assert listed_response.headers["X-Offset"] == "0"
    listed = listed_response.json()
    assert [item["id"] for item in listed] == [created["id"]]

    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert "event: runner_task.queued" in stream.text
    assert "event: runner_task.leased" in stream.text
    assert "event: runner_task.succeeded" in stream.text


def test_plan_step_runner_task_enforces_budget_and_attaches_evidence(
    client: TestClient,
) -> None:
    resource, incident, runner = _setup(client)
    incident = _move_to_investigating(client, incident)
    plan = client.post(
        f"/api/v1/incidents/{incident['id']}/plans",
        json={
            "objective": "Verify container health",
            "maxToolCalls": 1,
            "steps": [
                {
                    "title": "Collect container health",
                    "objective": "Collect bounded health evidence",
                    "kind": "observe",
                    "resourceScope": [resource["id"]],
                    "allowedCapabilities": ["docker.container_health"],
                    "risk": "read_only",
                }
            ],
        },
    ).json()
    step = plan["steps"][0]
    task_payload = {
        "incidentId": incident["id"],
        "planStepId": step["id"],
        "resourceId": resource["id"],
        "runnerId": runner["id"],
        "connector": "docker",
        "operation": "docker.container_health",
        "parameters": {"containerId": "api-01"},
        "idempotencyKey": "plan-step-health-001",
    }

    missing_step_payload = {**task_payload, "idempotencyKey": "missing-plan-step-001"}
    missing_step_payload.pop("planStepId")
    missing_step = client.post("/api/v1/runner-tasks", json=missing_step_payload)
    assert missing_step.status_code == 409
    assert missing_step.json()["error"]["code"] == "TASK_PLAN_STEP_REQUIRED"

    not_running = client.post("/api/v1/runner-tasks", json=task_payload)
    assert not_running.status_code == 409
    assert not_running.json()["error"]["code"] == "PLAN_STEP_NOT_RUNNING"

    plan = client.post(
        f"/api/v1/incidents/{incident['id']}/steps/{step['id']}/transitions",
        json={"target": "running", "expectedVersion": step["version"]},
    ).json()
    step = plan["steps"][0]
    created_response = client.post("/api/v1/runner-tasks", json=task_payload)
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["planStepId"] == step["id"]

    duplicate = client.post("/api/v1/runner-tasks", json=task_payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == created["id"]
    detail = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert detail["toolBudget"] == {"used": 1, "limit": 1}

    over_budget_payload = {**task_payload, "idempotencyKey": "plan-step-health-002"}
    over_budget = client.post("/api/v1/runner-tasks", json=over_budget_payload)
    assert over_budget.status_code == 409
    assert over_budget.json()["error"]["code"] == "TOOL_BUDGET_EXHAUSTED"

    authorization = {"Authorization": f"Bearer {runner['accessToken']}"}
    claimed = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/claim",
        json={"runnerFencingToken": runner["fencingToken"]},
        headers=authorization,
    ).json()["task"]
    completed = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/{created['id']}/complete",
        json={
            "completionId": str(uuid4()),
            "taskFencingToken": claimed["taskFencingToken"],
            "status": "succeeded",
            "summary": "Container is healthy",
            "output": '{"status":"healthy"}',
        },
        headers=authorization,
    ).json()["task"]
    assert completed["evidenceId"] is not None

    current_plan = client.get(f"/api/v1/incidents/{incident['id']}/plans/current").json()
    assert current_plan["steps"][0]["evidenceIds"] == [completed["evidenceId"]]
    filtered = client.get(
        "/api/v1/runner-tasks",
        params={"plan_step_id": step["id"]},
    ).json()
    assert [item["id"] for item in filtered] == [created["id"]]


def test_replan_and_terminal_step_cancel_active_runner_tasks(client: TestClient) -> None:
    resource, incident, runner = _setup(client)
    incident = _move_to_investigating(client, incident)

    def create_plan(objective: str) -> dict[str, object]:
        return client.post(
            f"/api/v1/incidents/{incident['id']}/plans",
            json={
                "objective": objective,
                "maxToolCalls": 5,
                "steps": [
                    {
                        "title": "Collect container health",
                        "objective": "Collect bounded health evidence",
                        "kind": "observe",
                        "resourceScope": [resource["id"]],
                        "allowedCapabilities": ["docker.container_health"],
                        "risk": "read_only",
                    }
                ],
            },
        ).json()

    first_plan = create_plan("Initial investigation path")
    first_step = first_plan["steps"][0]
    client.post(
        f"/api/v1/incidents/{incident['id']}/steps/{first_step['id']}/transitions",
        json={"target": "running", "expectedVersion": first_step["version"]},
    )
    first_task = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": incident["id"],
            "planStepId": first_step["id"],
            "resourceId": resource["id"],
            "runnerId": runner["id"],
            "connector": "docker",
            "operation": "docker.container_health",
            "parameters": {"containerId": "api-01"},
            "idempotencyKey": "replan-cancel-task-001",
        },
    ).json()

    second_plan = create_plan("Replanned investigation path")
    assert second_plan["version"] == 2
    cancelled_by_replan = client.get(
        "/api/v1/runner-tasks",
        params={"incident_id": incident["id"]},
    ).json()
    first_record = next(item for item in cancelled_by_replan if item["id"] == first_task["id"])
    assert first_record["status"] == "cancelled"
    assert first_record["errorCode"] == "PLAN_SUPERSEDED"

    second_step = second_plan["steps"][0]
    running_plan = client.post(
        f"/api/v1/incidents/{incident['id']}/steps/{second_step['id']}/transitions",
        json={"target": "running", "expectedVersion": second_step["version"]},
    ).json()
    second_step = running_plan["steps"][0]
    second_task = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": incident["id"],
            "planStepId": second_step["id"],
            "resourceId": resource["id"],
            "runnerId": runner["id"],
            "connector": "docker",
            "operation": "docker.container_health",
            "parameters": {"containerId": "api-01"},
            "idempotencyKey": "step-failed-cancel-task-001",
        },
    ).json()
    client.post(
        f"/api/v1/incidents/{incident['id']}/steps/{second_step['id']}/transitions",
        json={"target": "failed", "expectedVersion": second_step["version"]},
    )
    tasks = client.get(
        "/api/v1/runner-tasks",
        params={"incident_id": incident["id"]},
    ).json()
    second_record = next(item for item in tasks if item["id"] == second_task["id"])
    assert second_record["status"] == "cancelled"
    assert second_record["errorCode"] == "PLAN_STEP_FAILED"

    claim = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/claim",
        json={"runnerFencingToken": runner["fencingToken"]},
        headers={"Authorization": f"Bearer {runner['accessToken']}"},
    )
    assert claim.status_code == 200
    assert claim.json()["task"] is None
    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert stream.text.count("event: runner_task.cancelled") == 2


def test_runner_lease_expiry_loses_and_restores_owned_incident_observability(
    client: TestClient,
) -> None:
    resource, incident, runner = _setup(client)
    incident = _move_to_investigating(client, incident)
    unrelated = client.post(
        "/api/v1/incidents",
        json={
            "title": "Unrelated investigation",
            "severity": "medium",
            "resourceId": resource["id"],
        },
    ).json()
    unrelated = _move_to_investigating(client, unrelated)

    task = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": incident["id"],
            "resourceId": resource["id"],
            "runnerId": runner["id"],
            "connector": "docker",
            "operation": "docker.container_health",
            "parameters": {"containerId": "api-01"},
            "idempotencyKey": "lease-expiry-health-001",
            "maxAttempts": 2,
        },
    ).json()
    authorization = {"Authorization": f"Bearer {runner['accessToken']}"}
    claimed = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/claim",
        json={"runnerFencingToken": runner["fencingToken"]},
        headers=authorization,
    )
    assert claimed.status_code == 200
    assert claimed.json()["task"]["id"] == task["id"]

    async def expire_runner() -> int:
        database = client.app.state.database
        async with database.session_factory() as session:
            runner_id = UUID(str(runner["id"]))
            runner_record = await session.get(RunnerRecord, runner_id)
            lease_record = await session.scalar(
                select(RunnerLeaseRecord).where(RunnerLeaseRecord.runner_id == runner_id)
            )
            assert runner_record is not None
            assert lease_record is not None
            expired_at = datetime.now(UTC) - timedelta(seconds=1)
            runner_record.lease_expires_at = expired_at
            lease_record.expires_at = expired_at
            await session.commit()
        async with database.session_factory() as session:
            return await ObservabilityService(session).expire_stale_runners()

    assert asyncio.run(expire_runner()) == 1

    lost = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert lost["status"] == "OBSERVABILITY_LOST"
    assert lost["observabilityStatus"] == "lost"
    assert lost["observabilityRunnerId"] == runner["id"]
    assert lost["observabilityLostAt"] is not None
    still_investigating = client.get(f"/api/v1/incidents/{unrelated['id']}").json()
    assert still_investigating["status"] == "INVESTIGATING"

    recovered_task = client.get(
        "/api/v1/runner-tasks",
        params={"incident_id": incident["id"]},
    ).json()[0]
    assert recovered_task["status"] == "queued"
    assert recovered_task["runnerId"] is None
    assert recovered_task["taskFencingToken"] is None

    heartbeat = client.post(
        f"/runner/v1/runners/{runner['id']}/heartbeat",
        json={"heartbeatId": str(uuid4())},
        headers=authorization,
    )
    assert heartbeat.status_code == 200
    restored = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert restored["status"] == "INVESTIGATING"
    assert restored["observabilityStatus"] == "observable"
    assert restored["observabilityRunnerId"] is None
    assert restored["observabilityLostAt"] is None

    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert "event: incident.observability_lost" in stream.text
    assert "event: incident.observability_restored" in stream.text


def test_runner_task_rejects_write_operation(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": str(uuid4()),
            "resourceId": str(uuid4()),
            "connector": "docker",
            "operation": "docker.restart_container",
            "idempotencyKey": "unsafe-operation-001",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_runner_task_rejects_stale_runner_fencing_token(client: TestClient) -> None:
    _, _, runner = _setup(client)
    response = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/claim",
        json={"runnerFencingToken": runner["fencingToken"] + 1},
        headers={"Authorization": f"Bearer {runner['accessToken']}"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_RUNNER_FENCING_TOKEN"


def test_runner_task_server_side_redaction() -> None:
    output, redacted = RunnerTaskService._redact(
        "Authorization: Bearer abc123 password=hunter2 token=secret"
    )

    assert redacted is True
    assert "abc123" not in output
    assert "hunter2" not in output
    assert "secret" not in output


def test_runner_task_accepts_bounded_file_log_operation(client: TestClient) -> None:
    resource, incident, _ = _setup(client)

    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": incident["id"],
            "resourceId": resource["id"],
            "connector": "file",
            "operation": "file.tail",
            "parameters": {"path": "D:/logs/service.log", "lines": 200},
            "idempotencyKey": "bounded-file-tail-001",
        },
    )

    assert response.status_code == 201
    assert response.json()["operation"] == "file.tail"


def test_runner_task_rejects_connector_operation_mismatch(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": str(uuid4()),
            "resourceId": str(uuid4()),
            "connector": "file",
            "operation": "journal.query",
            "parameters": {"unit": "docker.service"},
            "idempotencyKey": "connector-mismatch-001",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_runner_task_accepts_bounded_http_probe(client: TestClient) -> None:
    resource, incident, _ = _setup(client)

    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": incident["id"],
            "resourceId": resource["id"],
            "connector": "http",
            "operation": "http.probe",
            "parameters": {
                "url": "http://api.internal.example:8000/health",
                "method": "GET",
                "expectedStatuses": [200, 204],
                "captureBody": False,
            },
            "idempotencyKey": "bounded-http-probe-001",
        },
    )

    assert response.status_code == 201
    assert response.json()["operation"] == "http.probe"


def test_runner_task_rejects_http_url_with_credentials(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": str(uuid4()),
            "resourceId": str(uuid4()),
            "connector": "http",
            "operation": "http.probe",
            "parameters": {"url": "http://user:pass@localhost:8000/health"},
            "idempotencyKey": "unsafe-http-probe-001",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_runner_task_accepts_bounded_prometheus_range_query(client: TestClient) -> None:
    resource, incident, _ = _setup(client)

    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": incident["id"],
            "resourceId": resource["id"],
            "connector": "prometheus",
            "operation": "prometheus.query_range",
            "parameters": {
                "baseUrl": "http://prometheus.internal.example:9090",
                "query": "rate(http_requests_total[5m])",
                "start": "2026-08-09T00:00:00Z",
                "end": "2026-08-09T01:00:00Z",
                "stepSeconds": 60,
            },
            "idempotencyKey": "prometheus-range-query-001",
        },
    )

    assert response.status_code == 201
    assert response.json()["operation"] == "prometheus.query_range"


def test_runner_task_rejects_excessive_prometheus_range(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": str(uuid4()),
            "resourceId": str(uuid4()),
            "connector": "prometheus",
            "operation": "prometheus.query_range",
            "parameters": {
                "baseUrl": "http://localhost:9090",
                "query": "up",
                "start": "2026-08-09T00:00:00Z",
                "end": "2026-08-09T07:00:00Z",
                "stepSeconds": 60,
            },
            "idempotencyKey": "prometheus-excessive-range-001",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("connector", "operation", "parameters", "idempotency_key"),
    [
        (
            "sqlite",
            "sqlite.integrity_check",
            {"path": "/lab/data/rag.db"},
            "sqlite-integrity-check-001",
        ),
        (
            "qdrant",
            "qdrant.query_smoke",
            {
                "baseUrl": "http://qdrant:6333",
                "collection": "documents",
                "vector": [0.1, 0.2, 0.3],
                "limit": 3,
            },
            "qdrant-query-smoke-001",
        ),
        (
            "rag",
            "rag.business_health",
            {
                "url": "http://rag-api:8000/api/ask",
                "question": "What is the local test document about?",
                "expectedTerms": ["OpsPilot"],
            },
            "rag-business-health-001",
        ),
    ],
)
def test_runner_task_accepts_lab_connector_contracts(
    client: TestClient,
    connector: str,
    operation: str,
    parameters: dict[str, object],
    idempotency_key: str,
) -> None:
    resource, incident, _ = _setup(client)

    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": incident["id"],
            "resourceId": resource["id"],
            "connector": connector,
            "operation": operation,
            "parameters": parameters,
            "idempotencyKey": idempotency_key,
        },
    )

    assert response.status_code == 201
    assert response.json()["operation"] == operation


@pytest.mark.parametrize(
    ("connector", "operation", "parameters"),
    [
        (
            "qdrant",
            "qdrant.collection",
            {"baseUrl": "http://qdrant:6333", "collection": "../../secrets"},
        ),
        (
            "qdrant",
            "qdrant.query_smoke",
            {"baseUrl": "http://qdrant:6333", "collection": "docs", "vector": []},
        ),
        (
            "rag",
            "rag.business_health",
            {"url": "http://rag-api:8000/ask?token=secret", "question": "health"},
        ),
        (
            "sqlite",
            "sqlite.health",
            {"path": "/lab/data/rag.db", "sql": "DROP TABLE documents"},
        ),
    ],
)
def test_runner_task_rejects_unsafe_lab_connector_parameters(
    client: TestClient,
    connector: str,
    operation: str,
    parameters: dict[str, object],
) -> None:
    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": str(uuid4()),
            "resourceId": str(uuid4()),
            "connector": connector,
            "operation": operation,
            "parameters": parameters,
            "idempotencyKey": f"unsafe-{connector}-{operation}-001",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_runner_task_accepts_host_snapshot(client: TestClient) -> None:
    resource, incident, _ = _setup(client)

    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": incident["id"],
            "resourceId": resource["id"],
            "connector": "host",
            "operation": "host.snapshot",
            "parameters": {},
            "idempotencyKey": "host-snapshot-001",
        },
    )

    assert response.status_code == 201
    assert response.json()["operation"] == "host.snapshot"


def test_runner_task_rejects_host_snapshot_parameters(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runner-tasks",
        json={
            "incidentId": str(uuid4()),
            "resourceId": str(uuid4()),
            "connector": "host",
            "operation": "host.snapshot",
            "parameters": {"command": "ps aux"},
            "idempotencyKey": "unsafe-host-snapshot-001",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
