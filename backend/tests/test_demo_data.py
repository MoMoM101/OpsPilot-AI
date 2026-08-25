import asyncio
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.application import create_app
from app.core.config import Settings
from app.storage import Base
from app.storage.models import IncidentRecord

BOOTSTRAP_TOKEN = "demo-data-bootstrap-token"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _app(*, environment: str = "test", enabled: bool = True) -> FastAPI:
    settings_values: dict[str, object] = {
        "environment": environment,
        "database_url": "sqlite+aiosqlite:///:memory:",
        "database_readiness_enabled": False,
        "control_plane_auth_enabled": True,
        "control_plane_bootstrap_token": BOOTSTRAP_TOKEN,
        "demo_data_enabled": enabled,
    }
    if environment == "production":
        settings_values.update(
            {
                "require_https": False,
                "alertmanager_webhook_token": "production-alert-token",
                "runner_bootstrap_token": "production-runner-token",
            }
        )
    app = create_app(Settings(**settings_values))  # type: ignore[arg-type]

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    return app


def _admin(client: TestClient) -> str:
    response = client.post(
        "/api/v1/principals",
        headers=_auth(BOOTSTRAP_TOKEN),
        json={
            "name": "demo-admin",
            "kind": "user",
            "role": "admin",
            "unrestrictedEnvironments": True,
        },
    )
    assert response.status_code == 201
    return str(response.json()["accessToken"])


def test_demo_lifecycle_is_admin_only_idempotent_and_generation_guarded() -> None:
    app = _app()
    with TestClient(app) as client:
        admin_token = _admin(client)
        admin_headers = _auth(admin_token)
        operator = client.post(
            "/api/v1/principals",
            headers=admin_headers,
            json={
                "name": "demo-operator-user",
                "kind": "user",
                "role": "operator",
                "unrestrictedEnvironments": True,
            },
        ).json()

        forbidden = client.get("/api/v1/demo/status", headers=_auth(operator["accessToken"]))
        initial_status = client.get("/api/v1/demo/status", headers=admin_headers)
        initialized = client.post("/api/v1/demo/initialize", headers=admin_headers)
        replayed = client.post("/api/v1/demo/initialize", headers=admin_headers)
        stale_cleanup = client.post(
            "/api/v1/demo/cleanup",
            headers=admin_headers,
            json={"expectedGeneration": 2},
        )

    assert forbidden.status_code == 403
    assert initial_status.json()["status"] == "inactive"
    assert initialized.status_code == 200
    assert initialized.json()["status"] == "active"
    assert initialized.json()["generation"] == 1
    assert initialized.json()["replayed"] is False
    assert len(initialized.json()["resourceIds"]) == 3
    assert len(initialized.json()["incidentIds"]) == 2
    assert replayed.json()["replayed"] is True
    assert replayed.json()["incidentIds"] == initialized.json()["incidentIds"]
    assert stale_cleanup.status_code == 409
    assert stale_cleanup.json()["error"]["code"] == "DEMO_GENERATION_CONFLICT"


def test_demo_cleanup_deletes_only_owned_incidents_and_supports_reinitialization() -> None:
    app = _app()
    with TestClient(app) as client:
        admin_headers = _auth(_admin(client))
        initialized = client.post("/api/v1/demo/initialize", headers=admin_headers).json()
        foreign_incident = client.post(
            "/api/v1/incidents",
            headers=admin_headers,
            json={
                "title": "Operator-owned incident in Demo workspace",
                "severity": "medium",
                "resourceId": initialized["resourceIds"][0],
            },
        ).json()
        cleaned = client.post(
            "/api/v1/demo/cleanup",
            headers=admin_headers,
            json={"expectedGeneration": 1},
        )
        incidents_after_cleanup = client.get(
            "/api/v1/incidents", headers=admin_headers
        ).json()
        cleanup_replay = client.post(
            "/api/v1/demo/cleanup",
            headers=admin_headers,
            json={"expectedGeneration": 1},
        )
        reinitialized = client.post("/api/v1/demo/initialize", headers=admin_headers)

    assert cleaned.status_code == 200
    assert cleaned.json()["deletedIncidentCount"] == 2
    assert cleaned.json()["status"] == "inactive"
    assert [item["id"] for item in incidents_after_cleanup] == [foreign_incident["id"]]
    assert cleanup_replay.json()["replayed"] is True
    assert reinitialized.status_code == 200
    assert reinitialized.json()["generation"] == 2
    assert reinitialized.json()["resourceIds"] == initialized["resourceIds"]
    assert set(reinitialized.json()["incidentIds"]).isdisjoint(initialized["incidentIds"])


def test_demo_drift_is_reported_and_never_silently_reinitialized() -> None:
    app = _app()
    with TestClient(app) as client:
        admin_headers = _auth(_admin(client))
        initialized = client.post("/api/v1/demo/initialize", headers=admin_headers).json()

        async def remove_owned_incident() -> None:
            async with app.state.database.session_factory() as session:
                await session.execute(
                        delete(IncidentRecord).where(
                        IncidentRecord.id == UUID(initialized["incidentIds"][0])
                    )
                )
                await session.commit()

        asyncio.run(remove_owned_incident())
        drifted = client.get("/api/v1/demo/status", headers=admin_headers)
        rejected = client.post("/api/v1/demo/initialize", headers=admin_headers)
        cleanup_rejected = client.post(
            "/api/v1/demo/cleanup",
            headers=admin_headers,
            json={"expectedGeneration": initialized["generation"]},
        )
        incidents_after_rejected_cleanup = client.get(
            "/api/v1/incidents", headers=admin_headers
        )

    assert drifted.json()["status"] == "drifted"
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "DEMO_DATA_DRIFT"
    assert cleanup_rejected.status_code == 409
    assert cleanup_rejected.json()["error"]["code"] == "DEMO_DATA_DRIFT"
    assert {
        item["id"] for item in incidents_after_rejected_cleanup.json()
    } == {initialized["incidentIds"][1]}


def test_demo_data_is_unavailable_in_production_even_when_flag_is_enabled() -> None:
    app = _app(environment="production", enabled=True)
    with TestClient(app) as client:
        admin_headers = _auth(_admin(client))
        status = client.get("/api/v1/demo/status", headers=admin_headers)
        rejected = client.post("/api/v1/demo/initialize", headers=admin_headers)

    assert status.status_code == 200
    assert status.json()["status"] == "unavailable"
    assert status.json()["reasonCode"] == "PRODUCTION_DISABLED"
    assert rejected.status_code == 404
    assert rejected.json()["error"]["code"] == "PRODUCTION_DISABLED"
