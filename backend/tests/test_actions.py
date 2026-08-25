import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.application import create_app
from app.core.config import Settings
from app.storage import ActionRequestRecord, Base


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'actions.db'}",
            database_readiness_enabled=False,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(app) as test_client:
        yield test_client


def _context(client: TestClient, *, approval_required: bool = True) -> dict[str, object]:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "Action environment", "slug": "action-environment"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "action-service",
            "kind": "service",
        },
    ).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Action incident",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    policy = client.post(
        "/api/v1/policies",
        json={
            "environmentId": environment["id"],
            "name": "controlled restart",
            "effect": "allow",
            "capabilities": ["container.restart"],
            "resourceIds": [resource["id"]],
            "approvalRequired": approval_required,
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
    return {
        "environment": environment,
        "resource": resource,
        "incident": incident,
        "policy": policy,
        "snapshot": snapshot,
    }


def _approved(client: TestClient, snapshot_id: str) -> dict[str, object]:
    approval = client.post(
        "/api/v1/approvals",
        json={
            "policyDecisionId": snapshot_id,
            "parameters": {"containerId": "api"},
        },
    ).json()
    response = client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        json={"decision": "approve", "expectedVersion": approval["version"]},
    )
    assert response.status_code == 200
    return response.json()


def test_action_offset_pages_are_stable_for_equal_timestamps(client: TestClient) -> None:
    context = _context(client)
    incident = context["incident"]
    environment = context["environment"]
    snapshot = context["snapshot"]
    assert isinstance(incident, dict)
    assert isinstance(environment, dict)
    assert isinstance(snapshot, dict)
    second_snapshot = client.post(
        "/api/v1/policies/evaluate",
        json={
            "environmentId": environment["id"],
            "incidentId": incident["id"],
            "resourceId": incident["resourceId"],
            "capability": "container.restart",
            "autonomyLevel": "L2",
            "risk": "medium",
        },
    ).json()
    actions: list[dict[str, object]] = []
    for index, decision in enumerate((snapshot, second_snapshot), start=1):
        approval = _approved(client, str(decision["snapshotId"]))
        created = client.post(
            "/api/v1/actions",
            json={
                "policyDecisionId": decision["snapshotId"],
                "approvalId": approval["id"],
                "parameters": {"containerId": "api"},
                "verificationCriteria": ["container health is healthy"],
                "idempotencyKey": f"stable-action-page-{index}",
            },
        )
        assert created.status_code == 201
        actions.append(created.json()["action"])

    async def align_timestamps() -> None:
        async with client.app.state.database.session_factory() as session:
            await session.execute(
                update(ActionRequestRecord)
                .where(ActionRequestRecord.id.in_([UUID(str(item["id"])) for item in actions]))
                .values(created_at=datetime(2026, 8, 25, tzinfo=UTC))
            )
            await session.commit()

    asyncio.run(align_timestamps())
    pages = [
        client.get("/api/v1/actions", params={"limit": 1, "offset": offset})
        for offset in range(2)
    ]
    page_ids = [page.json()[0]["id"] for page in pages]
    assert len(set(page_ids)) == 2
    assert set(page_ids) == {item["id"] for item in actions}
    assert all(page.headers["X-Total-Count"] == "2" for page in pages)


def test_approved_action_is_idempotent_and_cancellable(client: TestClient) -> None:
    context = _context(client)
    snapshot = context["snapshot"]
    assert isinstance(snapshot, dict)
    missing = client.post(
        "/api/v1/actions",
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "parameters": {"containerId": "api"},
            "verificationCriteria": ["container health is healthy"],
            "idempotencyKey": "restart-action-0001",
        },
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "ACTION_APPROVAL_REQUIRED"

    approval = _approved(client, str(snapshot["snapshotId"]))
    payload = {
        "policyDecisionId": snapshot["snapshotId"],
        "approvalId": approval["id"],
        "parameters": {"containerId": "api"},
        "verificationCriteria": ["container health is healthy"],
        "idempotencyKey": "restart-action-0001",
    }
    first = client.post("/api/v1/actions", json=payload)
    replay = client.post("/api/v1/actions", json=payload)
    assert first.status_code == replay.status_code == 201
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert replay.json()["action"]["id"] == first.json()["action"]["id"]

    reused_authorization = client.post(
        "/api/v1/actions",
        json={**payload, "idempotencyKey": "restart-action-second-consumption"},
    )
    assert reused_authorization.status_code == 409
    assert (
        reused_authorization.json()["error"]["code"]
        == "ACTION_AUTHORIZATION_ALREADY_CONSUMED"
    )

    conflicting = client.post(
        "/api/v1/actions",
        json={**payload, "verificationCriteria": ["different verification"]},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "ACTION_IDEMPOTENCY_CONFLICT"
    cancelled = client.post(
        f"/api/v1/actions/{first.json()['action']['id']}/cancel",
        json={"expectedVersion": 1, "reason": "Operator stopped the change"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["version"] == 2

    incident = context["incident"]
    assert isinstance(incident, dict)
    timeline = client.get(f"/api/v1/incidents/{incident['id']}").json()["timeline"]
    types = [item["type"] for item in timeline]
    assert types.count("action.requested") == 1
    assert "action.cancelled" in types


def test_action_parameters_must_match_approval(client: TestClient) -> None:
    context = _context(client)
    snapshot = context["snapshot"]
    assert isinstance(snapshot, dict)
    approval = _approved(client, str(snapshot["snapshotId"]))
    changed = client.post(
        "/api/v1/actions",
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "approvalId": approval["id"],
            "parameters": {"containerId": "database"},
            "verificationCriteria": ["container health is healthy"],
            "idempotencyKey": "restart-action-0002",
        },
    )
    assert changed.status_code == 422
    assert changed.json()["error"]["code"] == "ACTION_PARAMETERS_CHANGED"


def test_cross_capability_rollback_is_rejected_at_action_creation(
    client: TestClient,
) -> None:
    context = _context(client)
    snapshot = context["snapshot"]
    assert isinstance(snapshot, dict)
    approval = _approved(client, str(snapshot["snapshotId"]))
    response = client.post(
        "/api/v1/actions",
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "approvalId": approval["id"],
            "parameters": {"containerId": "api"},
            "verificationCriteria": ["container health is healthy"],
            "rollbackCapability": "traffic_probe.resume",
            "idempotencyKey": "restart-action-cross-rollback-0001",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ACTION_ROLLBACK_CAPABILITY_UNSUPPORTED"


def test_container_restart_cannot_claim_rollback_capability(client: TestClient) -> None:
    context = _context(client)
    snapshot = context["snapshot"]
    assert isinstance(snapshot, dict)
    approval = _approved(client, str(snapshot["snapshotId"]))
    response = client.post(
        "/api/v1/actions",
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "approvalId": approval["id"],
            "parameters": {"containerId": "api"},
            "verificationCriteria": ["container health is healthy"],
            "rollbackCapability": "container.restart",
            "idempotencyKey": "restart-action-fake-rollback-0001",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ACTION_ROLLBACK_CAPABILITY_UNSUPPORTED"


def test_action_revalidates_policy_and_supports_no_approval_rule(
    client: TestClient,
) -> None:
    context = _context(client, approval_required=False)
    snapshot = context["snapshot"]
    policy = context["policy"]
    environment = context["environment"]
    assert isinstance(snapshot, dict)
    assert isinstance(policy, dict)
    assert isinstance(environment, dict)
    allowed = client.post(
        "/api/v1/actions",
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "parameters": {"containerId": "api"},
            "verificationCriteria": ["container health is healthy"],
            "idempotencyKey": "restart-action-no-approval",
        },
    )
    assert allowed.status_code == 201
    assert allowed.json()["action"]["approvalId"] is None
    disabled = client.put(
        f"/api/v1/policies/{policy['id']}",
        json={
            "expectedVersion": policy["version"],
            "environmentId": environment["id"],
            "name": policy["name"],
            "effect": "allow",
            "enabled": False,
            "capabilities": ["container.restart"],
        },
    )
    assert disabled.status_code == 200
    blocked = client.post(
        "/api/v1/actions",
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "parameters": {"containerId": "api"},
            "verificationCriteria": ["container health is healthy"],
            "idempotencyKey": "restart-action-0003",
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "ACTION_AUTHORIZATION_ALREADY_CONSUMED"


def test_action_rejects_unsupported_capability_parameters(client: TestClient) -> None:
    context = _context(client, approval_required=False)
    snapshot = context["snapshot"]
    assert isinstance(snapshot, dict)
    invalid = client.post(
        "/api/v1/actions",
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "parameters": {"containerId": "api", "command": "rm -rf /"},
            "verificationCriteria": ["container health is healthy"],
            "idempotencyKey": "invalid-action-parameters",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "ACTION_PARAMETERS_INVALID"
