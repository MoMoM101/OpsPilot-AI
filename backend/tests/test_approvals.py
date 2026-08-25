import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.application import create_app
from app.core.config import Settings
from app.storage import ApprovalRecord, Base


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "approvals.db"
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


def _setup_snapshot(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "Approval environment", "slug": "approval-environment"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "approval-service",
            "kind": "service",
        },
    ).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Approval incident",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    policy = client.post(
        "/api/v1/policies",
        json={
            "environmentId": environment["id"],
            "name": "approved restart",
            "effect": "allow",
            "capabilities": ["container.restart"],
            "resourceIds": [resource["id"]],
            "approvalRequired": True,
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
    return {"environment": environment, "incident": incident, "policy": policy}, snapshot


def test_approval_offset_pages_are_stable_for_equal_timestamps(client: TestClient) -> None:
    context, first_snapshot = _setup_snapshot(client)
    incident = context["incident"]
    environment = context["environment"]
    assert isinstance(incident, dict)
    assert isinstance(environment, dict)
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
    approvals = [
        client.post(
            "/api/v1/approvals",
            json={"policyDecisionId": snapshot["snapshotId"]},
        ).json()
        for snapshot in (first_snapshot, second_snapshot)
    ]

    async def align_timestamps() -> None:
        async with client.app.state.database.session_factory() as session:
            await session.execute(
                update(ApprovalRecord)
                .where(ApprovalRecord.id.in_([UUID(item["id"]) for item in approvals]))
                .values(created_at=datetime(2026, 8, 25, tzinfo=UTC))
            )
            await session.commit()

    asyncio.run(align_timestamps())
    pages = [
        client.get("/api/v1/approvals", params={"limit": 1, "offset": offset})
        for offset in range(2)
    ]
    page_ids = [page.json()[0]["id"] for page in pages]
    assert len(set(page_ids)) == 2
    assert set(page_ids) == {item["id"] for item in approvals}
    assert all(page.headers["X-Total-Count"] == "2" for page in pages)


def test_approval_lifecycle_and_limited_parameter_edits(client: TestClient) -> None:
    context, snapshot = _setup_snapshot(client)
    created = client.post(
        "/api/v1/approvals",
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "parameters": {"container": "api", "timeoutSeconds": 30},
            "editableParameterKeys": ["timeoutSeconds"],
            "expiresInSeconds": 600,
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    duplicate = client.post(
        "/api/v1/approvals",
        json={"policyDecisionId": snapshot["snapshotId"]},
    )
    assert duplicate.status_code == 409

    forbidden_edit = client.post(
        f"/api/v1/approvals/{created.json()['id']}/decision",
        json={
            "decision": "approve",
            "expectedVersion": 1,
            "parameterEdits": {"container": "database"},
        },
    )
    assert forbidden_edit.status_code == 422
    approved = client.post(
        f"/api/v1/approvals/{created.json()['id']}/decision",
        json={
            "decision": "approve",
            "expectedVersion": 1,
            "comment": "Scoped restart approved",
            "parameterEdits": {"timeoutSeconds": 45},
        },
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["parameters"] == {"container": "api", "timeoutSeconds": 45}
    assert approved.json()["version"] == 2

    incident = client.get(f"/api/v1/incidents/{context['incident']['id']}").json()
    event_types = [item["type"] for item in incident["timeline"]]
    assert "approval.requested" in event_types
    assert "approval.resolved" in event_types


def test_policy_is_revalidated_before_approval(client: TestClient) -> None:
    context, snapshot = _setup_snapshot(client)
    approval = client.post(
        "/api/v1/approvals",
        json={"policyDecisionId": snapshot["snapshotId"]},
    ).json()
    policy = context["policy"]
    disabled = client.put(
        f"/api/v1/policies/{policy['id']}",
        json={
            "expectedVersion": policy["version"],
            "environmentId": context["environment"]["id"],
            "name": policy["name"],
            "effect": "allow",
            "enabled": False,
            "capabilities": ["container.restart"],
        },
    )
    assert disabled.status_code == 200
    rejected = client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        json={"decision": "approve", "expectedVersion": 1},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "POLICY_REVALIDATION_FAILED"
    pending = client.get("/api/v1/approvals", params={"status": "pending"}).json()
    assert [item["id"] for item in pending] == [approval["id"]]


def test_expired_approval_cannot_be_decided(client: TestClient) -> None:
    _, snapshot = _setup_snapshot(client)
    approval = client.post(
        "/api/v1/approvals",
        json={"policyDecisionId": snapshot["snapshotId"], "expiresInSeconds": 60},
    ).json()

    async def expire() -> None:
        async with client.app.state.database.session_factory() as session:
            record = await session.get(ApprovalRecord, UUID(approval["id"]))
            assert record is not None
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(expire())
    expired = client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        json={"decision": "approve", "expectedVersion": 1},
    )
    assert expired.status_code == 200
    assert expired.json()["status"] == "expired"
    assert expired.json()["version"] == 2


def test_approval_status_filter_is_applied_before_pagination(client: TestClient) -> None:
    context, first_snapshot = _setup_snapshot(client)
    fresh = client.post(
        "/api/v1/approvals",
        json={"policyDecisionId": first_snapshot["snapshotId"]},
    ).json()
    resource = client.get("/api/v1/resources").json()[0]
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Newer expiring approval",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    second_snapshot = client.post(
        "/api/v1/policies/evaluate",
        json={
            "environmentId": context["environment"]["id"],
            "incidentId": incident["id"],
            "resourceId": resource["id"],
            "capability": "container.restart",
            "autonomyLevel": "L2",
            "risk": "medium",
        },
    ).json()
    expired = client.post(
        "/api/v1/approvals",
        json={"policyDecisionId": second_snapshot["snapshotId"]},
    ).json()

    async def expire_latest() -> None:
        async with client.app.state.database.session_factory() as session:
            record = await session.get(ApprovalRecord, UUID(expired["id"]))
            assert record is not None
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(expire_latest())
    pending = client.get(
        "/api/v1/approvals", params={"status": "pending", "limit": 1}
    ).json()
    assert [item["id"] for item in pending] == [fresh["id"]]
    expired_page = client.get(
        "/api/v1/approvals", params={"status": "expired", "limit": 1}
    ).json()
    assert [item["id"] for item in expired_page] == [expired["id"]]
