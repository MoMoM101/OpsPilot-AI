import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.application import create_app
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.domain.actions import SUPPORTED_ACTION_CAPABILITIES
from app.services.action_capabilities import (
    ACTION_CAPABILITY_DEFINITIONS,
    AVAILABLE_ACTION_CAPABILITIES,
)
from app.services.actions import ActionRequestService
from app.services.connector_catalog import CONNECTOR_DEFINITIONS
from app.storage import Base

BOOTSTRAP_TOKEN = "action-capability-bootstrap-token"


def _app(*, authenticated: bool = False) -> TestClient:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
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


def _item(catalog: dict[str, object], capability: str) -> dict[str, object]:
    capabilities = catalog["capabilities"]
    assert isinstance(capabilities, list)
    return next(item for item in capabilities if item["capability"] == capability)


def test_catalog_describes_available_and_reserved_action_capabilities(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/action-capabilities")

    assert response.status_code == 200
    catalog = response.json()
    assert catalog["contractVersion"] == "1.0"
    assert {item["capability"] for item in catalog["capabilities"]} == set(
        SUPPORTED_ACTION_CAPABILITIES
    )

    restart = _item(catalog, "container.restart")
    assert restart == {
        "capability": "container.restart",
        "availability": "available",
        "effect": "mutation",
        "recommendedRisk": "medium",
        "executionConnector": "docker",
        "approvalMode": "policy",
        "verificationCriteriaRequired": True,
        "parameter": {
            "key": "containerId",
            "valueType": "string",
            "required": True,
            "minLength": 1,
            "maxLength": 300,
            "secret": False,
        },
        "verification": {
            "connector": "docker",
            "operation": "docker.container_health",
            "actionParameterKey": "containerId",
            "verificationParameterKey": "containerId",
        },
        "compensation": {
            "supported": False,
            "mode": "manual_escalation",
            "capability": None,
        },
    }
    health = _item(catalog, "health.check")
    assert health["effect"] == "observation"
    assert health["recommendedRisk"] == "read_only"
    assert health["compensation"]["mode"] == "not_applicable"
    reserved = _item(catalog, "service.reload")
    assert reserved["availability"] == "reserved"
    assert reserved["executionConnector"] is None
    assert reserved["verification"] is None
    assert reserved["compensation"]["mode"] == "unavailable"


def test_catalog_definitions_match_validation_and_bundled_runner_contract() -> None:
    definitions = {item.capability: item for item in ACTION_CAPABILITY_DEFINITIONS}
    assert set(definitions) == set(SUPPORTED_ACTION_CAPABILITIES)
    for capability in AVAILABLE_ACTION_CAPABILITIES:
        definition = definitions[capability]
        ActionRequestService.validate_capability_parameters(
            definition.capability, {definition.parameter_key: "resource"}
        )
        with pytest.raises(ApplicationError) as rollback_error:
            ActionRequestService.validate_rollback_capability(
                definition.capability, definition.capability
            )
        assert rollback_error.value.code == "ACTION_ROLLBACK_CAPABILITY_UNSUPPORTED"
    for definition in definitions.values():
        if definition.availability == "available":
            continue
        with pytest.raises(ApplicationError) as unavailable_error:
            ActionRequestService.validate_capability_parameters(
                definition.capability, {definition.parameter_key: "resource"}
            )
        assert unavailable_error.value.code == "ACTION_CAPABILITY_UNSUPPORTED"

    docker = next(item for item in CONNECTOR_DEFINITIONS if item.connector == "docker")
    available = set(AVAILABLE_ACTION_CAPABILITIES)
    assert available == set(docker.action_operations)
    assert all(
        definitions[capability].verification_operation in docker.observe_operations
        for capability in available
    )


def test_catalog_requires_authentication_and_is_visible_to_viewer() -> None:
    with _app(authenticated=True) as client:
        unauthorized = client.get("/api/v1/action-capabilities")
        bootstrap_headers = {"Authorization": f"Bearer {BOOTSTRAP_TOKEN}"}
        admin = client.post(
            "/api/v1/principals",
            headers=bootstrap_headers,
            json={
                "name": "capability-admin",
                "kind": "user",
                "role": "admin",
                "unrestrictedEnvironments": True,
            },
        ).json()
        viewer = client.post(
            "/api/v1/principals",
            headers={"Authorization": f"Bearer {admin['accessToken']}"},
            json={
                "name": "capability-viewer",
                "kind": "user",
                "role": "viewer",
                "unrestrictedEnvironments": True,
            },
        ).json()
        response = client.get(
            "/api/v1/action-capabilities",
            headers={"Authorization": f"Bearer {viewer['accessToken']}"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
