import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings
from app.storage import ActionExecutionRecord, ActionRequestRecord, Base, RunnerRecord


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'dispatcher.db'}",
            database_readiness_enabled=False,
            action_execution_lease_seconds=60,
            resource_lock_lease_seconds=60,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(app) as test_client:
        yield test_client


def _setup(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "Dispatcher", "slug": "dispatcher"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "dispatcher-service",
            "kind": "service",
        },
    ).json()
    client.post(
        "/api/v1/policies",
        json={
            "environmentId": environment["id"],
            "name": "dispatcher restart",
            "effect": "allow",
            "capabilities": ["container.restart"],
            "resourceIds": [resource["id"]],
        },
    )
    runner = client.post(
        "/runner/v1/runners/register",
        json={
            "name": "action-runner",
            "softwareVersion": "1.0.0",
            "environmentId": environment["id"],
            "capabilities": [
                {
                    "connector": "docker",
                    "contractVersion": "1.0",
                    "observe": ["docker.container_health"],
                    "actions": ["container.restart"],
                }
            ],
        },
    ).json()
    return {"environment": environment, "resource": resource}, runner


def _action(
    client: TestClient,
    context: dict[str, object],
    suffix: str,
    *,
    rollback: bool = False,
) -> dict[str, object]:
    environment = context["environment"]
    resource = context["resource"]
    assert isinstance(environment, dict) and isinstance(resource, dict)
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": f"Dispatch {suffix}",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    snapshot = client.post(
        "/api/v1/policies/evaluate",
        json={
            "environmentId": environment["id"],
            "incidentId": incident["id"],
            "resourceId": resource["id"],
            "capability": "container.restart",
            "autonomyLevel": "L2",
            "risk": "medium",
        },
    ).json()
    payload = {
        "policyDecisionId": snapshot["snapshotId"],
        "parameters": {"containerId": "api"},
        "verificationCriteria": ["container becomes healthy"],
        "idempotencyKey": f"dispatcher-action-{suffix}",
    }
    if rollback:
        payload["rollbackCapability"] = "container.restart"
    return client.post(
        "/api/v1/actions",
        json=payload,
    ).json()["action"]


def _headers(runner: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {runner['accessToken']}"}


def _mark_legacy_restart_rollback(client: TestClient, action_id: object) -> None:
    async def update() -> None:
        async with client.app.state.database.session_factory() as session:
            action = await session.get(ActionRequestRecord, UUID(str(action_id)))
            assert action is not None
            action.rollback_capability = "container.restart"
            await session.commit()

    asyncio.run(update())


def test_action_dispatch_claim_renew_and_complete(client: TestClient) -> None:
    context, runner = _setup(client)
    action = _action(client, context, "success")
    assert client.get("/api/v1/resource-locks").json() == []
    dispatch_operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/actions/{action_id}/dispatch"
    ]["post"]
    assert "requestBody" not in dispatch_operation
    dispatched = client.post(f"/api/v1/actions/{action['id']}/dispatch")
    assert dispatched.status_code == 200
    dispatched_body = dispatched.json()
    assert dispatched_body["status"] == "dispatching"
    assert "runnerId" not in dispatched_body
    assert "runnerFencingToken" not in dispatched_body
    assert "executionFencingToken" not in dispatched_body
    assert "resourceFencingToken" not in dispatched_body
    lock = client.get("/api/v1/resource-locks").json()[0]
    assert lock["actionRequestId"] == action["id"]
    assert "fencingToken" not in lock
    claim = client.post(
        f"/runner/v1/runners/{runner['id']}/actions/claim",
        headers=_headers(runner),
        json={"runnerFencingToken": runner["fencingToken"]},
    )
    assert claim.status_code == 200
    execution = claim.json()["execution"]
    assert execution["resourceFencingToken"] >= 1
    manual_release = client.post(
        f"/internal/v1/actions/{action['id']}/lock/release",
        json={"fencingToken": execution["resourceFencingToken"]},
    )
    assert manual_release.status_code == 409
    assert manual_release.json()["error"]["code"] == "RESOURCE_LOCK_MANUAL_CHANGE_FORBIDDEN"
    lease = {
        "executionFencingToken": execution["executionFencingToken"],
        "resourceFencingToken": execution["resourceFencingToken"],
    }
    assert (
        client.post(
            f"/runner/v1/runners/{runner['id']}/actions/{execution['executionId']}/renew",
            headers=_headers(runner),
            json=lease,
        ).status_code
        == 200
    )
    completion_id = str(uuid4())
    completed = client.post(
        f"/runner/v1/runners/{runner['id']}/actions/{execution['executionId']}/complete",
        headers=_headers(runner),
        json={
            **lease,
            "completionId": completion_id,
            "status": "succeeded",
            "summary": "Container restarted and reported healthy",
        },
    )
    assert completed.status_code == 200
    assert completed.json()["execution"]["status"] == "applied"
    assert completed.json()["duplicate"] is False
    duplicate = client.post(
        f"/runner/v1/runners/{runner['id']}/actions/{execution['executionId']}/complete",
        headers=_headers(runner),
        json={
            **lease,
            "completionId": completion_id,
            "status": "succeeded",
            "summary": "Container restarted and reported healthy",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    verification = client.get(f"/api/v1/actions/{action['id']}/verification").json()
    assert verification["status"] == "queued"
    assert verification["operation"] == "docker.container_health"
    assert verification["parameters"] == {"containerId": "api"}
    assert client.get("/api/v1/resource-locks").json()[0]["actionRequestId"] == action["id"]

    task = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/claim",
        headers=_headers(runner),
        json={"runnerFencingToken": runner["fencingToken"]},
    ).json()["task"]
    assert task["id"] == verification["runnerTaskId"]
    assert task["operation"] == "docker.container_health"
    verified = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/{task['id']}/complete",
        headers=_headers(runner),
        json={
            "completionId": str(uuid4()),
            "taskFencingToken": task["taskFencingToken"],
            "status": "succeeded",
            "summary": "Container is running and healthy",
            "output": '{"Status":"running","Health":{"Status":"healthy"}}',
        },
    )
    assert verified.status_code == 200
    final_verification = client.get(f"/api/v1/actions/{action['id']}/verification").json()
    assert final_verification["status"] == "passed"
    assert final_verification["evidenceId"] is not None
    assert client.get(f"/api/v1/actions/{action['id']}/execution").json()["status"] == "succeeded"
    assert client.get("/api/v1/resource-locks").json() == []


def test_dispatch_rolls_back_acquired_lock_when_no_runner_is_available(
    client: TestClient,
) -> None:
    context, runner = _setup(client)
    action = _action(client, context, "runner-unavailable")

    async def expire_runner() -> None:
        async with client.app.state.database.session_factory() as session:
            record = await session.get(RunnerRecord, UUID(str(runner["id"])))
            assert record is not None
            record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(expire_runner())
    response = client.post(f"/api/v1/actions/{action['id']}/dispatch")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACTION_RUNNER_UNAVAILABLE"
    assert client.get("/api/v1/resource-locks").json() == []
    assert client.get(f"/api/v1/actions/{action['id']}/execution").status_code == 404
    current = next(
        item for item in client.get("/api/v1/actions").json() if item["id"] == action["id"]
    )
    assert current["status"] == "ready"


def test_failed_restart_verification_does_not_offer_fake_compensation(
    client: TestClient,
) -> None:
    context, runner = _setup(client)
    action = _action(client, context, "verification-failed")
    client.post(f"/api/v1/actions/{action['id']}/dispatch")
    execution = client.post(
        f"/runner/v1/runners/{runner['id']}/actions/claim",
        headers=_headers(runner),
        json={"runnerFencingToken": runner["fencingToken"]},
    ).json()["execution"]
    client.post(
        f"/runner/v1/runners/{runner['id']}/actions/{execution['executionId']}/complete",
        headers=_headers(runner),
        json={
            "completionId": str(uuid4()),
            "executionFencingToken": execution["executionFencingToken"],
            "resourceFencingToken": execution["resourceFencingToken"],
            "status": "succeeded",
            "summary": "Restart command completed",
        },
    )

    for attempt in range(1, 4):
        task = client.post(
            f"/runner/v1/runners/{runner['id']}/tasks/claim",
            headers=_headers(runner),
            json={"runnerFencingToken": runner["fencingToken"]},
        ).json()["task"]
        assert task["attempt"] == attempt
        response = client.post(
            f"/runner/v1/runners/{runner['id']}/tasks/{task['id']}/complete",
            headers=_headers(runner),
            json={
                "completionId": str(uuid4()),
                "taskFencingToken": task["taskFencingToken"],
                "status": "failed",
                "summary": "Container remains unhealthy",
                "errorCode": "HEALTH_CHECK_FAILED",
            },
        )
        assert response.status_code == 200
        expected = "queued" if attempt < 3 else "failed"
        assert response.json()["task"]["status"] == expected

    verification = client.get(f"/api/v1/actions/{action['id']}/verification").json()
    assert verification["status"] == "failed"
    assert verification["compensationRequired"] is False
    assert verification["errorCode"] == "HEALTH_CHECK_FAILED"
    execution_status = client.get(f"/api/v1/actions/{action['id']}/execution").json()["status"]
    assert execution_status == "verification_failed"
    held = client.get("/api/v1/resource-locks").json()
    assert held[0]["actionRequestId"] == action["id"]
    assert held[0]["reconciliationRequired"] is True


def test_expired_execution_becomes_unknown_until_reconciled(client: TestClient) -> None:
    context, runner = _setup(client)
    action = _action(client, context, "unknown")
    client.post(f"/api/v1/actions/{action['id']}/dispatch")
    claim = client.post(
        f"/runner/v1/runners/{runner['id']}/actions/claim",
        headers=_headers(runner),
        json={"runnerFencingToken": runner["fencingToken"]},
    ).json()["execution"]

    async def expire() -> None:
        async with client.app.state.database.session_factory() as session:
            record = await session.get(ActionExecutionRecord, UUID(claim["executionId"]))
            assert record is not None
            record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(expire())
    recovered = client.post(
        f"/api/v1/actions/{action['id']}/dispatch",
    )
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "unknown"
    current_action = next(
        item for item in client.get("/api/v1/actions").json() if item["id"] == action["id"]
    )
    held = client.get("/api/v1/resource-locks").json()
    assert held[0]["actionRequestId"] == action["id"]
    reconciled = client.post(
        f"/api/v1/actions/{action['id']}/reconcile",
        json={
            "expectedVersion": current_action["version"],
            "outcome": "failed",
            "summary": "Target state proves the restart did not complete",
            "errorCode": "RECONCILED_NOT_APPLIED",
        },
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "failed"
    assert client.get("/api/v1/resource-locks").json() == []


def test_compensation_requires_independent_approval_and_reuses_runner_protocol(
    client: TestClient,
) -> None:
    context, runner = _setup(client)
    action = _action(client, context, "compensation-success")
    _mark_legacy_restart_rollback(client, action["id"])
    client.post(f"/api/v1/actions/{action['id']}/dispatch")
    assert "fencingToken" not in client.get("/api/v1/resource-locks").json()[0]
    action_execution = client.post(
        f"/runner/v1/runners/{runner['id']}/actions/claim",
        headers=_headers(runner),
        json={"runnerFencingToken": runner["fencingToken"]},
    ).json()["execution"]
    client.post(
        f"/runner/v1/runners/{runner['id']}/actions/{action_execution['executionId']}/complete",
        headers=_headers(runner),
        json={
            "completionId": str(uuid4()),
            "executionFencingToken": action_execution["executionFencingToken"],
            "resourceFencingToken": action_execution["resourceFencingToken"],
            "status": "succeeded",
            "summary": "Restart applied",
        },
    )
    for _ in range(3):
        task = client.post(
            f"/runner/v1/runners/{runner['id']}/tasks/claim",
            headers=_headers(runner),
            json={"runnerFencingToken": runner["fencingToken"]},
        ).json()["task"]
        client.post(
            f"/runner/v1/runners/{runner['id']}/tasks/{task['id']}/complete",
            headers=_headers(runner),
            json={
                "completionId": str(uuid4()),
                "taskFencingToken": task["taskFencingToken"],
                "status": "failed",
                "summary": "Health remains degraded",
                "errorCode": "HEALTH_CHECK_FAILED",
            },
        )

    created = client.post(
        f"/api/v1/actions/{action['id']}/compensation",
        json={
            "parameters": {"containerId": "api"},
            "idempotencyKey": "compensation-success-key",
        },
    )
    assert created.status_code == 201
    compensation = created.json()
    assert compensation["status"] == "pending"
    assert compensation["capability"] == "container.restart"
    duplicate = client.post(
        f"/api/v1/actions/{action['id']}/compensation",
        json={
            "parameters": {"containerId": "api"},
            "idempotencyKey": "compensation-success-key",
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == compensation["id"]
    premature = client.post(
        f"/api/v1/compensations/{compensation['id']}/dispatch",
        json={
            "expectedVersion": compensation["version"],
        },
    )
    assert premature.status_code == 409

    approved = client.post(
        f"/api/v1/compensations/{compensation['id']}/decision",
        json={
            "decision": "approve",
            "expectedVersion": compensation["version"],
            "comment": "Operator approved bounded compensation",
        },
    ).json()
    dispatched = client.post(
        f"/api/v1/compensations/{compensation['id']}/dispatch",
        json={
            "expectedVersion": approved["version"],
        },
    )
    assert dispatched.status_code == 200
    assert "runnerId" not in dispatched.json()
    assert "runnerFencingToken" not in dispatched.json()
    assert "executionFencingToken" not in dispatched.json()
    assert "resourceFencingToken" not in dispatched.json()
    compensation_execution = client.post(
        f"/runner/v1/runners/{runner['id']}/actions/claim",
        headers=_headers(runner),
        json={"runnerFencingToken": runner["fencingToken"]},
    ).json()["execution"]
    assert compensation_execution["executionKind"] == "compensation"
    assert compensation_execution["compensationId"] == compensation["id"]
    assert compensation_execution["capability"] == "container.restart"
    assert compensation_execution["resourceFencingToken"] >= 1
    compensation_completion_id = str(uuid4())
    completion_payload = {
        "completionId": compensation_completion_id,
        "executionFencingToken": compensation_execution["executionFencingToken"],
        "resourceFencingToken": compensation_execution["resourceFencingToken"],
        "status": "succeeded",
        "summary": "Compensation completed",
    }
    completed = client.post(
        f"/runner/v1/runners/{runner['id']}/actions/{compensation_execution['executionId']}/complete",
        headers=_headers(runner),
        json=completion_payload,
    )
    assert completed.status_code == 200
    assert completed.json()["execution"]["status"] == "succeeded"
    duplicate_completion = client.post(
        f"/runner/v1/runners/{runner['id']}/actions/{compensation_execution['executionId']}/complete",
        headers=_headers(runner),
        json=completion_payload,
    )
    assert duplicate_completion.status_code == 200
    assert duplicate_completion.json()["duplicate"] is True
    current_action = next(
        item for item in client.get("/api/v1/actions").json() if item["id"] == action["id"]
    )
    assert current_action["status"] == "compensated"
    assert client.get("/api/v1/resource-locks").json() == []
