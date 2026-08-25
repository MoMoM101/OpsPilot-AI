import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings
from app.storage import Base
from app.storage.models import RunnerRecord


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
            runner_lease_seconds=60,
            runner_token_rotation_seconds=60,
            runner_token_ttl_seconds=300,
            runner_token_grace_seconds=30,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(app) as test_client:
        yield test_client


def _registration_payload() -> dict[str, object]:
    return {
        "name": "runner-prod-01",
        "softwareVersion": "0.1.0",
        "capabilities": [
            {
                "connector": "docker",
                "contractVersion": "1.0",
                "observe": ["docker.health", "docker.logs"],
                "actions": ["docker.restart_container"],
            }
        ],
        "labels": {"region": "cn-east-1", "api_token": "must-not-be-stored"},
    }


def test_runner_registration_and_idempotent_heartbeat(client: TestClient) -> None:
    registration_response = client.post(
        "/runner/v1/runners/register",
        json=_registration_payload(),
    )
    assert registration_response.status_code == 201
    registration = registration_response.json()
    assert registration["status"] == "online"
    assert registration["fencingToken"] == 1
    assert registration["accessToken"]
    assert registration["labels"]["api_token"] == "[REDACTED]"

    heartbeat_id = str(uuid4())
    heartbeat_response = client.post(
        f"/runner/v1/runners/{registration['id']}/heartbeat",
        json={"heartbeatId": heartbeat_id, "softwareVersion": "0.1.1"},
        headers={"Authorization": f"Bearer {registration['accessToken']}"},
    )
    assert heartbeat_response.status_code == 200
    heartbeat = heartbeat_response.json()
    assert heartbeat["duplicate"] is False
    assert heartbeat["fencingToken"] == 2
    assert heartbeat["version"] == 2

    duplicate_response = client.post(
        f"/runner/v1/runners/{registration['id']}/heartbeat",
        json={"heartbeatId": heartbeat_id, "softwareVersion": "0.1.1"},
        headers={"Authorization": f"Bearer {registration['accessToken']}"},
    )
    assert duplicate_response.status_code == 200
    duplicate = duplicate_response.json()
    assert duplicate["duplicate"] is True
    assert duplicate["fencingToken"] == 2
    assert duplicate["version"] == 2

    runners_response = client.get("/api/v1/runners", params={"status": "online"})
    assert runners_response.headers["X-Total-Count"] == "1"
    assert runners_response.headers["X-Limit"] == "50"
    assert runners_response.headers["X-Offset"] == "0"
    runners = runners_response.json()
    assert len(runners) == 1
    assert runners[0]["softwareVersion"] == "0.1.1"
    assert "accessToken" not in runners[0]


def test_runner_heartbeat_rejects_invalid_token(client: TestClient) -> None:
    registration = client.post(
        "/runner/v1/runners/register",
        json=_registration_payload(),
    ).json()

    response = client.post(
        f"/runner/v1/runners/{registration['id']}/heartbeat",
        json={"heartbeatId": str(uuid4())},
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_RUNNER_TOKEN"


def test_runner_heartbeat_rotates_token_and_recovers_lost_response(
    client: TestClient,
) -> None:
    registration = client.post(
        "/runner/v1/runners/register",
        json=_registration_payload(),
    ).json()

    async def make_rotation_due() -> None:
        async with client.app.state.database.session_factory() as session:
            runner = await session.get(RunnerRecord, UUID(registration["id"]))
            assert runner is not None
            runner.token_issued_at = datetime.now(UTC) - timedelta(seconds=61)
            await session.commit()

    asyncio.run(make_rotation_due())
    old_headers = {"Authorization": f"Bearer {registration['accessToken']}"}
    rotated = client.post(
        f"/runner/v1/runners/{registration['id']}/heartbeat",
        json={"heartbeatId": str(uuid4())},
        headers=old_headers,
    )
    assert rotated.status_code == 200
    rotated_token = rotated.json()["accessToken"]
    assert rotated_token and rotated_token != registration["accessToken"]
    assert rotated.json()["tokenExpiresAt"]

    recovered = client.post(
        f"/runner/v1/runners/{registration['id']}/heartbeat",
        json={"heartbeatId": str(uuid4())},
        headers=old_headers,
    )
    assert recovered.status_code == 200
    recovered_token = recovered.json()["accessToken"]
    assert recovered_token and recovered_token != rotated_token

    accepted = client.post(
        f"/runner/v1/runners/{registration['id']}/heartbeat",
        json={"heartbeatId": str(uuid4())},
        headers={"Authorization": f"Bearer {recovered_token}"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["accessToken"] is None


def test_runner_rejects_expired_current_token(client: TestClient) -> None:
    registration = client.post(
        "/runner/v1/runners/register",
        json=_registration_payload(),
    ).json()

    async def expire_token() -> None:
        async with client.app.state.database.session_factory() as session:
            runner = await session.get(RunnerRecord, UUID(registration["id"]))
            assert runner is not None
            runner.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(expire_token())
    response = client.post(
        f"/runner/v1/runners/{registration['id']}/heartbeat",
        json={"heartbeatId": str(uuid4())},
        headers={"Authorization": f"Bearer {registration['accessToken']}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "RUNNER_TOKEN_EXPIRED"


def test_runner_capability_rejects_arbitrary_shell(client: TestClient) -> None:
    payload = _registration_payload()
    payload["name"] = "runner-unsafe-01"
    payload["capabilities"] = [
        {
            "connector": "system",
            "contractVersion": "1.0",
            "actions": ["system.run_shell"],
        }
    ]

    response = client.post("/runner/v1/runners/register", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_runner_bootstrap_token_is_enforced() -> None:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
            runner_bootstrap_token="expected-bootstrap-token",
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/runner/v1/runners/register",
            json=_registration_payload(),
            headers={"X-OpsPilot-Runner-Bootstrap-Token": "wrong-token"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_RUNNER_BOOTSTRAP_TOKEN"
