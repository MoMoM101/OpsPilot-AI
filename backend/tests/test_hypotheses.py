import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings
from app.storage import Base


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


def _incident(client: TestClient) -> dict[str, object]:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "Hypothesis test", "slug": "hypothesis-test"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "vector-db-test-01",
            "kind": "qdrant",
        },
    ).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Vector search latency increased",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    incident = client.post(
        f"/api/v1/incidents/{incident['id']}/transitions",
        json={"target": "CORRELATING", "expectedVersion": incident["version"]},
    ).json()
    return incident


def test_hypothesis_lifecycle_primary_selection_and_sse(client: TestClient) -> None:
    incident = _incident(client)
    first_response = client.post(
        f"/api/v1/incidents/{incident['id']}/hypotheses",
        json={"summary": "Qdrant segment loading is slow", "confidence": 60},
    )
    assert first_response.status_code == 201
    first = first_response.json()
    assert first["ordinal"] == 1
    assert first["status"] == "proposed"
    assert first["version"] == 1

    second = client.post(
        f"/api/v1/incidents/{incident['id']}/hypotheses",
        json={"summary": "Embedding service is timing out", "confidence": 80},
    ).json()
    assert second["ordinal"] == 2

    detail = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert detail["hypothesis"]["id"] == second["id"]
    assert detail["hypothesis"]["confidence"] == 80

    updated_response = client.patch(
        f"/api/v1/incidents/{incident['id']}/hypotheses/{first['id']}",
        json={
            "expectedVersion": first["version"],
            "confidence": 95,
            "status": "confirmed",
        },
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["status"] == "confirmed"
    assert updated["version"] == 2

    detail = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert detail["hypothesis"]["id"] == first["id"]
    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["incidents"][0]["hypothesis"]["id"] == first["id"]

    stale = client.patch(
        f"/api/v1/incidents/{incident['id']}/hypotheses/{first['id']}",
        json={"expectedVersion": 1, "confidence": 50},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "HYPOTHESIS_VERSION_CONFLICT"

    rejected = client.patch(
        f"/api/v1/incidents/{incident['id']}/hypotheses/{first['id']}",
        json={"expectedVersion": 2, "status": "rejected"},
    )
    assert rejected.status_code == 200
    detail = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert detail["hypothesis"]["id"] == second["id"]

    hypotheses_response = client.get(
        f"/api/v1/incidents/{incident['id']}/hypotheses",
        params={"limit": 1, "offset": 1},
    )
    assert hypotheses_response.headers["X-Total-Count"] == "2"
    assert hypotheses_response.headers["X-Limit"] == "1"
    assert hypotheses_response.headers["X-Offset"] == "1"
    assert len(hypotheses_response.json()) == 1

    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert "event: hypothesis.created" in stream.text
    assert "event: hypothesis.updated" in stream.text


def test_hypothesis_rejects_unowned_evidence(client: TestClient) -> None:
    incident = _incident(client)
    response = client.post(
        f"/api/v1/incidents/{incident['id']}/hypotheses",
        json={
            "summary": "Unsupported hypothesis",
            "confidence": 40,
            "supportingEvidenceIds": [str(uuid4())],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "HYPOTHESIS_EVIDENCE_NOT_FOUND"
