import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings
from app.domain.actions import ActionRequestStatus
from app.domain.incidents import IncidentStatus
from app.storage import Base
from app.storage.models import ActionRequestRecord, IncidentRecord, ResourceLockRecord


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(app) as test_client:
        yield test_client


def _evaluate(
    client: TestClient,
    *,
    environment_id: str,
    incident_id: str,
    resource_id: str,
    capability: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/policies/evaluate",
        json={
            "environmentId": environment_id,
            "incidentId": incident_id,
            "resourceId": resource_id,
            "capability": capability,
            "autonomyLevel": "L2",
            "risk": "medium",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_dashboard_returns_real_runner_and_safety_aggregates(client: TestClient) -> None:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "Dashboard", "slug": "dashboard"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "dashboard-api",
            "kind": "service",
        },
    ).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Dashboard safety incident",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    for name, capability, approval_required in (
        ("automatic restart", "container.restart", False),
        ("approved health check", "health.check", True),
    ):
        policy = client.post(
            "/api/v1/policies",
            json={
                "environmentId": environment["id"],
                "name": name,
                "effect": "allow",
                "capabilities": [capability],
                "resourceIds": [resource["id"]],
                "approvalRequired": approval_required,
            },
        )
        assert policy.status_code == 201

    action_snapshot = _evaluate(
        client,
        environment_id=environment["id"],
        incident_id=incident["id"],
        resource_id=resource["id"],
        capability="container.restart",
    )
    action_response = client.post(
        "/api/v1/actions",
        json={
            "policyDecisionId": action_snapshot["snapshotId"],
            "parameters": {"containerId": "dashboard-api"},
            "verificationCriteria": ["container is healthy"],
            "idempotencyKey": "dashboard-action-0001",
        },
    )
    assert action_response.status_code == 201
    action = action_response.json()["action"]

    approval_snapshot = _evaluate(
        client,
        environment_id=environment["id"],
        incident_id=incident["id"],
        resource_id=resource["id"],
        capability="health.check",
    )
    approval = client.post(
        "/api/v1/approvals",
        json={
            "policyDecisionId": approval_snapshot["snapshotId"],
            "parameters": {"target": "dashboard-api"},
        },
    )
    assert approval.status_code == 201

    runner = client.post(
        "/runner/v1/runners/register",
        json={
            "name": "dashboard-runner",
            "softwareVersion": "0.1.0",
            "environmentId": environment["id"],
            "capabilities": [],
        },
    )
    assert runner.status_code == 201

    async def set_attention_state() -> None:
        now = datetime.now(UTC)
        async with client.app.state.database.session_factory() as session:
            action_record = await session.get(ActionRequestRecord, UUID(action["id"]))
            incident_record = await session.get(IncidentRecord, UUID(incident["id"]))
            assert action_record is not None
            assert incident_record is not None
            action_record.status = ActionRequestStatus.UNKNOWN
            action_record.updated_at = now
            incident_record.status = IncidentStatus.OBSERVABILITY_LOST
            incident_record.updated_at = now
            session.add(
                ResourceLockRecord(
                    environment_id=UUID(environment["id"]),
                    resource_id=UUID(resource["id"]),
                    incident_id=UUID(incident["id"]),
                    action_request_id=UUID(action["id"]),
                    fencing_token=1,
                    acquired_at=now,
                    renewed_at=now,
                    expires_at=now + timedelta(minutes=5),
                    reconciliation_required=False,
                )
            )
            await session.commit()

    asyncio.run(set_attention_state())
    dashboard = client.get("/api/v1/dashboard")

    assert dashboard.status_code == 200
    assert dashboard.json()["runnerOnline"] == 1
    assert dashboard.json()["runnerTotal"] == 1
    assert dashboard.json()["safety"] == {
        "pendingApprovals": 1,
        "activeResourceLocks": 1,
        "unknownActions": 1,
        "actionsRequiringAttention": 1,
        "observabilityLostIncidents": 1,
    }
