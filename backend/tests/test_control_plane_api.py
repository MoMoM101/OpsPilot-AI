import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings
from app.storage import Base
from app.storage.repositories import IncidentRepository


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


def test_create_resource_and_incident_flow(client: TestClient) -> None:
    environment_response = client.post(
        "/api/v1/environments",
        json={"name": "生产", "slug": "production"},
    )
    assert environment_response.status_code == 201
    environment = environment_response.json()
    assert environment["slug"] == "production"
    assert "createdAt" in environment

    resource_response = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "qdrant-prod-01",
            "kind": "qdrant",
            "criticality": "critical",
            "attributes": {"region": "cn-east-1"},
        },
    )
    assert resource_response.status_code == 201
    resource = resource_response.json()

    incident_response = client.post(
        "/api/v1/incidents",
        json={
            "title": "Qdrant service unavailable",
            "severity": "critical",
            "resourceId": resource["id"],
            "owner": "on-call",
        },
    )
    assert incident_response.status_code == 201
    incident = incident_response.json()
    assert incident["status"] == "DETECTED"
    assert incident["version"] == 1
    assert incident["resource"] == "qdrant-prod-01"
    assert incident["environment"] == "生产"
    assert incident["timeline"][0]["type"] == "incident.created"

    transition_response = client.post(
        f"/api/v1/incidents/{incident['id']}/transitions",
        json={
            "target": "CORRELATING",
            "expectedVersion": 1,
            "actorId": "on-call",
        },
    )
    assert transition_response.status_code == 200
    transitioned = transition_response.json()
    assert transitioned["status"] == "CORRELATING"
    assert transitioned["version"] == 2
    assert transitioned["timeline"][0]["type"] == "incident.status_changed"

    list_response = client.get("/api/v1/incidents", params={"status": "CORRELATING"})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [incident["id"]]


def test_incident_transition_rejects_stale_version(client: TestClient) -> None:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "测试", "slug": "test"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "api-test-01",
            "kind": "service",
        },
    ).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "API returns 500",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    response = client.post(
        f"/api/v1/incidents/{incident['id']}/transitions",
        json={"target": "CORRELATING", "expectedVersion": 99},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INCIDENT_VERSION_CONFLICT"
    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert "event: incident.created" in stream.text
    assert "event: incident.status_changed" not in stream.text
    invalid_cursor = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
        headers={"Last-Event-ID": "not-an-integer"},
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["error"]["code"] == "INVALID_LAST_EVENT_ID"


def test_incident_detail_bounds_timeline_and_timeline_endpoint_paginates(
    client: TestClient,
) -> None:
    environment = client.post(
        "/api/v1/environments", json={"name": "Timeline", "slug": "timeline"}
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "timeline-service",
            "kind": "service",
        },
    ).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Long-running incident",
            "severity": "medium",
            "resourceId": resource["id"],
        },
    ).json()

    async def add_historical_events() -> None:
        async with client.app.state.database.session_factory() as session:
            repository = IncidentRepository(session)
            base = datetime.now(UTC) + timedelta(days=1)
            for index in range(105):
                await repository.add_event(
                    UUID(str(incident["id"])),
                    f"synthetic.{index:03d}",
                    base + timedelta(seconds=index),
                    "system",
                    None,
                    {"index": index},
                )
            await session.commit()

    asyncio.run(add_historical_events())
    detail = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert detail["timelineTotal"] == 106
    assert detail["timelineTruncated"] is True
    assert len(detail["timeline"]) == 100
    assert detail["timeline"][0]["type"] == "synthetic.104"

    page = client.get(
        f"/api/v1/incidents/{incident['id']}/timeline",
        params={"limit": 10, "offset": 100},
    )
    assert page.status_code == 200
    assert page.headers["X-Total-Count"] == "106"
    assert page.headers["X-Limit"] == "10"
    assert page.headers["X-Offset"] == "100"
    assert [item["type"] for item in page.json()] == [
        "synthetic.004",
        "synthetic.003",
        "synthetic.002",
        "synthetic.001",
        "synthetic.000",
        "incident.created",
    ]


def test_investigation_plan_lifecycle_and_dashboard(client: TestClient) -> None:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "预发布", "slug": "staging"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "embedding-staging-01",
            "kind": "service",
        },
    ).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Embedding timeout",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    created_event_cursor = incident["eventCursor"]
    assert created_event_cursor > 0

    for target in ("CORRELATING", "INVESTIGATING"):
        incident = client.post(
            f"/api/v1/incidents/{incident['id']}/transitions",
            json={"target": target, "expectedVersion": incident["version"]},
        ).json()

    invalid_plan = client.post(
        f"/api/v1/incidents/{incident['id']}/plans",
        json={
            "objective": "Invalid forward dependency",
            "steps": [
                {
                    "title": "Invalid first step",
                    "objective": "Must not reference a future step",
                    "kind": "observe",
                    "dependencies": ["2"],
                    "risk": "read_only",
                }
            ],
        },
    )
    assert invalid_plan.status_code == 422
    assert invalid_plan.json()["error"]["code"] == "INVALID_PLAN_DEPENDENCY"

    plan_response = client.post(
        f"/api/v1/incidents/{incident['id']}/plans",
        json={
            "objective": "Find the source of embedding latency",
            "maxToolCalls": 20,
            "maxDurationSeconds": 600,
            "steps": [
                {
                    "title": "Check service health",
                    "objective": "Collect health and latency evidence",
                    "kind": "observe",
                    "risk": "read_only",
                },
                {
                    "title": "Analyze recent logs",
                    "objective": "Identify timeout patterns",
                    "kind": "analyze",
                    "dependencies": ["1"],
                    "risk": "read_only",
                },
            ],
        },
    )
    assert plan_response.status_code == 201
    plan = plan_response.json()
    assert plan["version"] == 1
    assert plan["status"] == "active"
    assert len(plan["steps"]) == 2

    first_step = plan["steps"][0]
    second_step = plan["steps"][1]
    unmet_dependency = client.post(
        f"/api/v1/incidents/{incident['id']}/steps/{second_step['id']}/transitions",
        json={"target": "running", "expectedVersion": second_step["version"]},
    )
    assert unmet_dependency.status_code == 409
    assert unmet_dependency.json()["error"]["code"] == "PLAN_STEP_DEPENDENCIES_UNMET"

    plan = client.post(
        f"/api/v1/incidents/{incident['id']}/steps/{first_step['id']}/transitions",
        json={"target": "running", "expectedVersion": first_step["version"]},
    ).json()
    first_step = plan["steps"][0]
    assert first_step["attempts"] == 1

    unknown_evidence = client.post(
        f"/api/v1/incidents/{incident['id']}/steps/{first_step['id']}/transitions",
        json={
            "target": "completed",
            "expectedVersion": first_step["version"],
            "evidenceIds": [str(uuid4())],
        },
    )
    assert unknown_evidence.status_code == 422
    assert unknown_evidence.json()["error"]["code"] == "PLAN_STEP_EVIDENCE_NOT_FOUND"

    plan = client.post(
        f"/api/v1/incidents/{incident['id']}/steps/{first_step['id']}/transitions",
        json={
            "target": "completed",
            "expectedVersion": first_step["version"],
            "resultSummary": "Service is reachable but latency is elevated",
        },
    ).json()
    second_step = plan["steps"][1]
    plan = client.post(
        f"/api/v1/incidents/{incident['id']}/steps/{second_step['id']}/transitions",
        json={"target": "skipped", "expectedVersion": second_step["version"]},
    ).json()
    assert plan["status"] == "completed"

    detail = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert detail["planVersion"] == 1
    assert detail["toolBudget"] == {"used": 0, "limit": 20}
    assert len(detail["steps"]) == 2
    assert detail["traceId"]
    assert detail["eventCursor"] > created_event_cursor

    dashboard_response = client.get("/api/v1/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["activeTasks"] == 1
    assert dashboard["incidents"][0]["id"] == incident["id"]

    stream_response = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert "event: incident.created" in stream_response.text
    assert "event: plan.created" in stream_response.text
    assert "event: step.updated" in stream_response.text
    event_ids = [
        int(line.removeprefix("id: "))
        for line in stream_response.text.splitlines()
        if line.startswith("id: ")
    ]
    assert event_ids == sorted(event_ids)
    assert detail["eventCursor"] == event_ids[-1]

    recovered_after_snapshot = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
        headers={"Last-Event-ID": str(created_event_cursor)},
    )
    assert recovered_after_snapshot.status_code == 200
    assert "event: incident.status_changed" in recovered_after_snapshot.text
    assert "event: plan.created" in recovered_after_snapshot.text

    replay_response = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
        headers={"Last-Event-ID": str(detail["eventCursor"])},
    )
    assert replay_response.status_code == 200
    assert replay_response.text == ""
