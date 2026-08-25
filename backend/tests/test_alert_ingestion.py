import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import update

from app.core.application import create_app
from app.core.config import Settings
from app.storage import AlertRecord, Base


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


def _alert_payload(
    *,
    fingerprint: str,
    starts_at: str,
    status: str = "firing",
    instance: str = "qdrant-prod-01",
) -> dict[str, object]:
    return {
        "version": "4",
        "groupKey": "qdrant-health",
        "status": status,
        "receiver": "opspilot",
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "QdrantUnavailable",
                    "instance": instance,
                    "severity": "critical",
                },
                "annotations": {
                    "summary": "Qdrant service is unavailable",
                    "api_token": "must-not-be-stored",
                },
                "startsAt": starts_at,
                "endsAt": "2026-08-09T02:10:00Z" if status == "resolved" else None,
                "generatorURL": "http://prometheus/graph",
                "fingerprint": fingerprint,
            }
        ],
    }


def test_alertmanager_deduplicates_and_correlates_incidents(client: TestClient) -> None:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "生产", "slug": "production"},
    ).json()
    client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "qdrant-prod-01",
            "kind": "qdrant",
            "criticality": "critical",
        },
    )
    first_payload = _alert_payload(
        fingerprint="fp-qdrant-1",
        starts_at="2026-08-09T02:00:00Z",
    )

    first = client.post("/api/v1/alerts/webhook/alertmanager", json=first_payload)
    assert first.status_code == 202
    assert first.json() == {
        "received": 1,
        "created": 1,
        "deduplicated": 0,
        "incidentsCreated": 1,
        "incidentsCorrelated": 0,
        "unmatched": 0,
    }

    duplicate = client.post("/api/v1/alerts/webhook/alertmanager", json=first_payload)
    assert duplicate.status_code == 202
    assert duplicate.json()["deduplicated"] == 1
    alerts = client.get("/api/v1/alerts", params={"status": "firing"}).json()
    assert len(alerts) == 1
    assert alerts[0]["occurrenceCount"] == 2
    assert alerts[0]["annotations"]["api_token"] == "[REDACTED]"

    incidents = client.get("/api/v1/incidents").json()
    assert len(incidents) == 1
    incident_id = incidents[0]["id"]

    second = client.post(
        "/api/v1/alerts/webhook/alertmanager",
        json=_alert_payload(
            fingerprint="fp-qdrant-2",
            starts_at="2026-08-09T02:05:00Z",
        ),
    )
    assert second.status_code == 202
    assert second.json()["incidentsCorrelated"] == 1
    assert len(client.get("/api/v1/incidents").json()) == 1

    async def align_alert_timestamps() -> None:
        async with client.app.state.database.session_factory() as session:
            await session.execute(
                update(AlertRecord).values(last_seen_at=datetime(2026, 8, 25, tzinfo=UTC))
            )
            await session.commit()

    asyncio.run(align_alert_timestamps())
    alert_pages = [
        client.get(
            "/api/v1/alerts",
            params={"status": "firing", "limit": 1, "offset": offset},
        )
        for offset in range(2)
    ]
    alert_page_ids = [page.json()[0]["id"] for page in alert_pages]
    assert len(set(alert_page_ids)) == 2
    assert all(page.headers["X-Total-Count"] == "2" for page in alert_pages)

    resolved = client.post(
        "/api/v1/alerts/webhook/alertmanager",
        json=_alert_payload(
            fingerprint="fp-qdrant-1",
            starts_at="2026-08-09T02:00:00Z",
            status="resolved",
        ),
    )
    assert resolved.status_code == 202
    assert resolved.json()["deduplicated"] == 1
    resolved_alerts = client.get("/api/v1/alerts", params={"status": "resolved"}).json()
    assert len(resolved_alerts) == 1

    stream = client.get(
        f"/api/v1/incidents/{incident_id}/stream",
        params={"follow": "false"},
    ).text
    assert "event: incident.created" in stream
    assert stream.count("event: incident.correlated") == 2
    assert "event: alert.resolved" in stream


def test_unmatched_alert_is_persisted_without_incident(client: TestClient) -> None:
    response = client.post(
        "/api/v1/alerts/webhook/alertmanager",
        json=_alert_payload(
            fingerprint="fp-unknown",
            starts_at="2026-08-09T03:00:00Z",
            instance="unknown-host",
        ),
    )

    assert response.status_code == 202
    assert response.json()["unmatched"] == 1
    assert client.get("/api/v1/incidents").json() == []


def test_webhook_token_is_required_when_configured() -> None:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
            alertmanager_webhook_token="expected-secret",
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/alerts/webhook/alertmanager",
            json=_alert_payload(
                fingerprint="fp-auth",
                starts_at="2026-08-09T04:00:00Z",
            ),
            headers={"X-OpsPilot-Webhook-Token": "wrong-secret"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_WEBHOOK_TOKEN"


def test_production_requires_webhook_token() -> None:
    with pytest.raises(ValidationError, match="webhook token"):
        Settings(environment="production", alertmanager_webhook_token=None)
