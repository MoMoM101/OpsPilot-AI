import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings
from app.storage import Base


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "policies.db"
    app = create_app(
        Settings(
            environment="test",
            database_url=f"sqlite+aiosqlite:///{database_path}",
            database_readiness_enabled=False,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(app) as test_client:
        yield test_client


def _environment_and_resource(client: TestClient, suffix: str = "one") -> tuple[str, str]:
    environment = client.post(
        "/api/v1/environments",
        json={"name": f"Policy {suffix}", "slug": f"policy-{suffix}"},
    )
    assert environment.status_code == 201
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment.json()["id"],
            "name": f"service-{suffix}",
            "kind": "service",
        },
    )
    assert resource.status_code == 201
    return environment.json()["id"], resource.json()["id"]


def test_policy_dry_run_defaults_to_deny_and_explains_match(client: TestClient) -> None:
    environment_id, resource_id = _environment_and_resource(client)
    request = {
        "environmentId": environment_id,
        "resourceId": resource_id,
        "capability": "container.restart",
        "autonomyLevel": "L2",
        "risk": "medium",
    }

    default_decision = client.post("/api/v1/policies/dry-run", json=request)
    assert default_decision.status_code == 200
    assert default_decision.json() == {
        "allowed": False,
        "approvalRequired": False,
        "matchedRuleId": None,
        "matchedRuleName": None,
        "effect": None,
        "reason": "No enabled Policy rule matched; default deny applies",
        "matchedRuleVersion": None,
        "remainingExecutions": None,
    }

    allow = client.post(
        "/api/v1/policies",
        json={
            "environmentId": environment_id,
            "name": "approve controlled restarts",
            "priority": 100,
            "effect": "allow",
            "autonomyLevels": ["L2"],
            "riskLevels": ["medium"],
            "capabilities": ["container.restart"],
            "resourceIds": [resource_id],
            "approvalRequired": True,
        },
    )
    assert allow.status_code == 201

    decision = client.post("/api/v1/policies/dry-run", json=request)
    assert decision.status_code == 200
    assert decision.json()["allowed"] is True
    assert decision.json()["approvalRequired"] is True
    assert decision.json()["matchedRuleId"] == allow.json()["id"]
    assert decision.json()["effect"] == "allow"


def test_higher_priority_deny_wins_and_scope_is_validated(client: TestClient) -> None:
    environment_id, resource_id = _environment_and_resource(client)
    other_environment_id, other_resource_id = _environment_and_resource(client, "two")
    invalid_scope = client.post(
        "/api/v1/policies",
        json={
            "environmentId": environment_id,
            "name": "invalid cross environment",
            "effect": "allow",
            "resourceIds": [other_resource_id],
        },
    )
    assert invalid_scope.status_code == 422
    assert invalid_scope.json()["error"]["code"] == "POLICY_RESOURCE_SCOPE_INVALID"

    for name, priority, effect in (
        ("allow all restarts", 10, "allow"),
        ("deny medium changes", 20, "deny"),
    ):
        response = client.post(
            "/api/v1/policies",
            json={
                "environmentId": environment_id,
                "name": name,
                "priority": priority,
                "effect": effect,
                "riskLevels": ["medium"] if effect == "deny" else [],
                "capabilities": ["container.restart"],
            },
        )
        assert response.status_code == 201

    first_page = client.get(
        "/api/v1/policies",
        params={"environmentId": environment_id, "limit": 1, "offset": 0},
    )
    assert first_page.status_code == 200
    assert len(first_page.json()) == 1
    assert first_page.headers["X-Total-Count"] == "2"
    assert first_page.headers["X-Limit"] == "1"
    assert first_page.headers["X-Offset"] == "0"
    assert first_page.json()[0]["name"] == "deny medium changes"

    decision = client.post(
        "/api/v1/policies/dry-run",
        json={
            "environmentId": environment_id,
            "resourceId": resource_id,
            "capability": "container.restart",
            "autonomyLevel": "L1",
            "risk": "medium",
        },
    )
    assert decision.json()["allowed"] is False
    assert decision.json()["matchedRuleName"] == "deny medium changes"
    assert other_environment_id != environment_id


def test_policy_update_uses_version_and_disabled_rule_no_longer_matches(
    client: TestClient,
) -> None:
    environment_id, resource_id = _environment_and_resource(client)
    created = client.post(
        "/api/v1/policies",
        json={
            "environmentId": environment_id,
            "name": "temporary allow",
            "effect": "allow",
            "capabilities": ["health.check"],
        },
    ).json()
    update = {
        "expectedVersion": created["version"],
        "environmentId": environment_id,
        "name": created["name"],
        "effect": "allow",
        "enabled": False,
        "capabilities": ["health.check"],
    }
    disabled = client.put(f"/api/v1/policies/{created['id']}", json=update)
    assert disabled.status_code == 200
    assert disabled.json()["version"] == 2
    assert disabled.json()["enabled"] is False
    conflict = client.put(f"/api/v1/policies/{created['id']}", json=update)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "POLICY_RULE_VERSION_CONFLICT"

    decision = client.post(
        "/api/v1/policies/dry-run",
        json={
            "environmentId": environment_id,
            "resourceId": resource_id,
            "capability": "health.check",
            "autonomyLevel": "L1",
            "risk": "read_only",
        },
    )
    assert decision.json()["allowed"] is False
    assert decision.json()["matchedRuleId"] is None


def test_recorded_policy_evaluation_enforces_per_incident_limit(
    client: TestClient,
) -> None:
    environment_id, resource_id = _environment_and_resource(client)
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Policy limit incident",
            "severity": "high",
            "resourceId": resource_id,
        },
    )
    assert incident.status_code == 201
    rule = client.post(
        "/api/v1/policies",
        json={
            "environmentId": environment_id,
            "name": "one restart per incident",
            "effect": "allow",
            "capabilities": ["container.restart"],
            "resourceIds": [resource_id],
            "approvalRequired": True,
            "maxExecutionsPerIncident": 1,
        },
    )
    assert rule.status_code == 201
    request = {
        "environmentId": environment_id,
        "incidentId": incident.json()["id"],
        "resourceId": resource_id,
        "capability": "container.restart",
        "autonomyLevel": "L2",
        "risk": "medium",
    }
    first = client.post("/api/v1/policies/evaluate", json=request)
    second = client.post("/api/v1/policies/evaluate", json=request)
    assert first.status_code == second.status_code == 200
    assert first.json()["allowed"] is True
    assert first.json()["approvalRequired"] is True
    assert first.json()["remainingExecutions"] == 0
    assert first.json()["snapshotId"] != second.json()["snapshotId"]
    assert second.json()["allowed"] is True

    approval = client.post(
        "/api/v1/approvals",
        json={
            "policyDecisionId": first.json()["snapshotId"],
            "parameters": {"containerId": "api"},
        },
    ).json()
    approved = client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        json={"decision": "approve", "expectedVersion": approval["version"]},
    ).json()
    action = client.post(
        "/api/v1/actions",
        json={
            "policyDecisionId": first.json()["snapshotId"],
            "approvalId": approved["id"],
            "parameters": {"containerId": "api"},
            "verificationCriteria": ["container becomes healthy"],
            "idempotencyKey": "policy-limit-action-0001",
        },
    )
    assert action.status_code == 201

    third = client.post("/api/v1/policies/evaluate", json=request)
    assert third.status_code == 200
    assert third.json()["allowed"] is False
    assert third.json()["approvalRequired"] is False
    assert "execution limit" in third.json()["reason"]


def test_policy_maintenance_window_fails_closed_outside_utc_day(
    client: TestClient,
) -> None:
    environment_id, resource_id = _environment_and_resource(client)
    excluded_day = (datetime.now(UTC).weekday() + 1) % 7
    created = client.post(
        "/api/v1/policies",
        json={
            "environmentId": environment_id,
            "name": "weekday window",
            "effect": "allow",
            "capabilities": ["service.reload"],
            "maintenanceDays": [excluded_day],
            "maintenanceStartMinute": 0,
            "maintenanceEndMinute": 1440,
        },
    )
    assert created.status_code == 201
    decision = client.post(
        "/api/v1/policies/dry-run",
        json={
            "environmentId": environment_id,
            "resourceId": resource_id,
            "capability": "service.reload",
            "autonomyLevel": "L1",
            "risk": "low",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["allowed"] is False
    assert "maintenance window is closed" in decision.json()["reason"]
