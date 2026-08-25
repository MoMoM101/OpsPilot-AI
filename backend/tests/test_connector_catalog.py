import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings
from app.services.connector_catalog import catalog_observe_operations, runner_read_operations
from app.storage import Base
from app.storage.models import RunnerRecord

BOOTSTRAP_TOKEN = "connector-catalog-bootstrap-token"


def _app(*, authenticated: bool = False) -> TestClient:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
            runner_lease_seconds=60,
            control_plane_auth_enabled=authenticated,
            control_plane_bootstrap_token=BOOTSTRAP_TOKEN if authenticated else None,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _app() as test_client:
        yield test_client


def _environment(client: TestClient, name: str, headers: dict[str, str] | None = None) -> str:
    response = client.post(
        "/api/v1/environments",
        headers=headers,
        json={"name": name, "slug": name.lower().replace(" ", "-")},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _register(
    client: TestClient,
    *,
    name: str,
    environment_id: str | None,
    capabilities: list[dict[str, object]],
    labels: dict[str, str] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/runner/v1/runners/register",
        json={
            "name": name,
            "softwareVersion": "0.1.0",
            "environmentId": environment_id,
            "capabilities": capabilities,
            "labels": labels or {},
        },
    )
    assert response.status_code == 201
    return response.json()


def _capability(
    connector: str,
    observe: list[str],
    *,
    actions: list[str] | None = None,
    contract_version: str = "1.0",
) -> dict[str, object]:
    return {
        "connector": connector,
        "contractVersion": contract_version,
        "observe": observe,
        "actions": actions or [],
    }


def _item(catalog: dict[str, object], connector: str) -> dict[str, object]:
    connectors = catalog["connectors"]
    assert isinstance(connectors, list)
    return next(item for item in connectors if item["connector"] == connector)


def test_catalog_covers_every_control_plane_read_operation() -> None:
    assert catalog_observe_operations() == runner_read_operations()


def test_catalog_reports_environment_specific_readiness_without_sensitive_runner_data(
    client: TestClient,
) -> None:
    first_environment = _environment(client, "First")
    second_environment = _environment(client, "Second")
    _register(
        client,
        name="global-runner",
        environment_id=None,
        capabilities=[
            _capability(
                "docker",
                [
                    "docker.list_containers",
                    "docker.inspect_container",
                    "docker.container_logs",
                    "docker.container_health",
                ],
                actions=["container.restart", "health.check"],
            ),
            _capability("host", ["host.snapshot"]),
        ],
        labels={"api_token": "catalog-must-not-return-this-secret"},
    )
    _register(
        client,
        name="second-only-runner",
        environment_id=second_environment,
        capabilities=[_capability("http", ["http.probe"])],
    )

    first = client.get(
        "/api/v1/connectors", params={"environmentId": first_environment}
    )
    second = client.get(
        "/api/v1/connectors", params={"environmentId": second_environment}
    )

    assert first.status_code == 200
    assert len(first.json()["connectors"]) == 10
    assert _item(first.json(), "docker")["availability"]["status"] == "ready"
    assert _item(first.json(), "http")["availability"]["status"] == "not_configured"
    assert _item(second.json(), "http")["availability"]["status"] == "ready"
    assert "catalog-must-not-return-this-secret" not in first.text
    assert "global-runner" not in first.text


def test_catalog_distinguishes_partial_incompatible_and_offline_runners(
    client: TestClient,
) -> None:
    environment_id = _environment(client, "Compatibility")
    partial = _register(
        client,
        name="partial-runner",
        environment_id=environment_id,
        capabilities=[_capability("prometheus", ["prometheus.query"])],
    )
    _register(
        client,
        name="future-runner",
        environment_id=environment_id,
        capabilities=[
            _capability("qdrant", ["qdrant.health"], contract_version="2.0")
        ],
    )
    offline = _register(
        client,
        name="offline-runner",
        environment_id=environment_id,
        capabilities=[_capability("file", ["file.tail"])],
    )

    async def force_offline() -> None:
        async with client.app.state.database.session_factory() as session:
            record = await session.get(RunnerRecord, UUID(str(offline["id"])))
            assert record is not None
            record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(force_offline())
    response = client.get(
        "/api/v1/connectors", params={"environmentId": environment_id}
    )
    catalog = response.json()

    assert response.status_code == 200
    prometheus = _item(catalog, "prometheus")["availability"]
    assert prometheus["status"] == "partial"
    assert prometheus["readyObserveOperations"] == ["prometheus.query"]
    qdrant = _item(catalog, "qdrant")["availability"]
    assert qdrant["status"] == "incompatible"
    assert qdrant["incompatibleRunnerCount"] == 1
    file_connector = _item(catalog, "file")["availability"]
    assert file_connector["status"] == "offline"
    assert file_connector["onlineRunnerCount"] == 0
    assert partial["id"]


def test_catalog_environment_filter_cannot_escape_operator_scope() -> None:
    with _app(authenticated=True) as client:
        bootstrap_headers = {"Authorization": f"Bearer {BOOTSTRAP_TOKEN}"}
        admin = client.post(
            "/api/v1/principals",
            headers=bootstrap_headers,
            json={
                "name": "catalog-admin",
                "kind": "user",
                "role": "admin",
                "unrestrictedEnvironments": True,
            },
        ).json()
        admin_headers = {"Authorization": f"Bearer {admin['accessToken']}"}
        visible_environment = _environment(client, "Visible", admin_headers)
        hidden_environment = _environment(client, "Hidden", admin_headers)
        operator = client.post(
            "/api/v1/principals",
            headers=admin_headers,
            json={
                "name": "catalog-operator",
                "kind": "user",
                "role": "operator",
                "environmentIds": [visible_environment],
                "unrestrictedEnvironments": False,
            },
        ).json()
        _register(
            client,
            name="visible-runner",
            environment_id=visible_environment,
            capabilities=[_capability("host", ["host.snapshot"])],
        )
        _register(
            client,
            name="hidden-runner",
            environment_id=hidden_environment,
            capabilities=[_capability("http", ["http.probe"])],
        )
        operator_headers = {"Authorization": f"Bearer {operator['accessToken']}"}
        visible = client.get("/api/v1/connectors", headers=operator_headers)
        escaped = client.get(
            "/api/v1/connectors",
            headers=operator_headers,
            params={"environmentId": hidden_environment},
        )

    assert visible.status_code == 200
    assert _item(visible.json(), "host")["availability"]["status"] == "ready"
    assert _item(visible.json(), "http")["availability"]["status"] == "not_configured"
    assert escaped.status_code == 404
    assert escaped.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"
