import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings
from app.storage import Base, ResourceLockRecord


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'resource-locks.db'}",
            database_readiness_enabled=False,
            resource_lock_lease_seconds=60,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(app) as test_client:
        yield test_client


def _actions(client: TestClient) -> tuple[dict[str, object], dict[str, object], str]:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "Lock environment", "slug": "lock-environment"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "locked-service",
            "kind": "service",
        },
    ).json()
    policy = client.post(
        "/api/v1/policies",
        json={
            "environmentId": environment["id"],
            "name": "lockable restart",
            "effect": "allow",
            "capabilities": ["container.restart"],
            "resourceIds": [resource["id"]],
        },
    )
    assert policy.status_code == 201
    actions: list[dict[str, object]] = []
    for ordinal in (1, 2):
        incident = client.post(
            "/api/v1/incidents",
            json={
                "title": f"Competing incident {ordinal}",
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
        response = client.post(
            "/api/v1/actions",
            json={
                "policyDecisionId": snapshot["snapshotId"],
                "parameters": {"containerId": "api"},
                "verificationCriteria": ["container becomes healthy"],
                "idempotencyKey": f"resource-lock-action-{ordinal}",
            },
        )
        assert response.status_code == 201
        actions.append(response.json()["action"])
    return actions[0], actions[1], str(resource["id"])


def test_resource_lock_excludes_competing_action_and_fences_stale_owner(
    client: TestClient,
) -> None:
    first_action, second_action, resource_id = _actions(client)
    first = client.post(f"/internal/v1/actions/{first_action['id']}/lock")
    duplicate = client.post(f"/internal/v1/actions/{first_action['id']}/lock")
    assert first.status_code == duplicate.status_code == 201
    assert first.json()["duplicate"] is False
    assert duplicate.json()["duplicate"] is True
    assert first.json()["lock"]["fencingToken"] == 1

    conflict = client.post(f"/internal/v1/actions/{second_action['id']}/lock")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "RESOURCE_LOCK_CONFLICT"
    renewed = client.post(
        f"/internal/v1/actions/{first_action['id']}/lock/renew",
        json={"fencingToken": 1},
    )
    assert renewed.status_code == 200
    released = client.post(
        f"/internal/v1/actions/{first_action['id']}/lock/release",
        json={"fencingToken": 1},
    )
    assert released.status_code == 200

    takeover = client.post(f"/internal/v1/actions/{second_action['id']}/lock")
    assert takeover.status_code == 201
    assert takeover.json()["lock"]["fencingToken"] == 2
    assert takeover.json()["lock"]["resourceId"] == resource_id
    timeline = client.get(f"/api/v1/incidents/{second_action['incidentId']}").json()["timeline"]
    acquired_event = next(item for item in timeline if item["type"] == "resource_lock.acquired")
    assert acquired_event["payload"]["actionId"] == second_action["id"]
    assert "fencingToken" not in acquired_event["payload"]
    stale = client.post(
        f"/internal/v1/actions/{first_action['id']}/lock/renew",
        json={"fencingToken": 1},
    )
    assert stale.status_code in {404, 409}
    assert stale.json()["error"]["code"] in {
        "RESOURCE_LOCK_NOT_FOUND",
        "RESOURCE_LOCK_FENCED",
    }


def test_expired_lock_can_be_taken_over_with_higher_token(client: TestClient) -> None:
    first_action, second_action, _ = _actions(client)
    acquired = client.post(f"/internal/v1/actions/{first_action['id']}/lock").json()

    async def expire() -> None:
        async with client.app.state.database.session_factory() as session:
            record = await session.get(ResourceLockRecord, UUID(acquired["lock"]["id"]))
            assert record is not None
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(expire())
    takeover = client.post(f"/internal/v1/actions/{second_action['id']}/lock")
    assert takeover.status_code == 201
    assert takeover.json()["duplicate"] is False
    assert takeover.json()["lock"]["fencingToken"] == 2
    active_response = client.get("/api/v1/resource-locks")
    assert active_response.headers["X-Total-Count"] == "1"
    assert active_response.headers["X-Limit"] == "100"
    assert active_response.headers["X-Offset"] == "0"
    active = active_response.json()
    assert [item["actionRequestId"] for item in active] == [second_action["id"]]
    assert "fencingToken" not in active[0]


def test_cancelling_action_releases_its_resource_lock(client: TestClient) -> None:
    first_action, second_action, _ = _actions(client)
    acquired = client.post(f"/internal/v1/actions/{first_action['id']}/lock")
    assert acquired.status_code == 201
    cancelled = client.post(
        f"/api/v1/actions/{first_action['id']}/cancel",
        json={"expectedVersion": 1, "reason": "No longer required"},
    )
    assert cancelled.status_code == 200
    takeover = client.post(f"/internal/v1/actions/{second_action['id']}/lock")
    assert takeover.status_code == 201
    assert takeover.json()["lock"]["fencingToken"] == 2


def test_lock_acquisition_revalidates_current_policy(client: TestClient) -> None:
    first_action, _, _ = _actions(client)
    policies = client.get(
        "/api/v1/policies",
        params={"environmentId": first_action["environmentId"]},
    ).json()
    policy = policies[0]
    disabled = client.put(
        f"/api/v1/policies/{policy['id']}",
        json={
            "expectedVersion": policy["version"],
            "environmentId": policy["environmentId"],
            "name": policy["name"],
            "effect": policy["effect"],
            "enabled": False,
            "capabilities": policy["capabilities"],
            "resourceIds": policy["resourceIds"],
        },
    )
    assert disabled.status_code == 200
    blocked = client.post(f"/internal/v1/actions/{first_action['id']}/lock")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "POLICY_REVALIDATION_FAILED"
