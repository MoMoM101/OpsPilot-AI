import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.services.lab import LabControllerClient


def _scenario(*, active: bool = False) -> dict[str, object]:
    return {
        "id": "qdrant_down",
        "title": "Qdrant unavailable",
        "description": "Disable the RAG Qdrant proxy",
        "status": "active" if active else "ready",
        "version": 1,
        "active": active,
        "supported": True,
    }


@pytest.mark.asyncio
async def test_lab_client_lists_and_mutates_scenarios_with_private_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[_scenario()])
        return httpx.Response(200, json={"scenario": _scenario(active=True), "replayed": False})

    client = LabControllerClient(
        enabled=True,
        base_url="http://lab-controller:8010/",
        token="private-lab-token",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    scenarios = await client.list_scenarios()
    mutation = await client.mutate("qdrant_down", "inject", "inject-key-123")

    assert scenarios[0].id == "qdrant_down"
    assert mutation.scenario.active is True
    assert [request.url.path for request in requests] == [
        "/scenarios",
        "/scenarios/qdrant_down/inject",
    ]
    assert all(
        request.headers["X-OpsPilot-Lab-Token"] == "private-lab-token"
        for request in requests
    )
    assert requests[1].content == b'{"idempotencyKey":"inject-key-123"}'


@pytest.mark.asyncio
async def test_disabled_lab_does_not_contact_controller() -> None:
    client = LabControllerClient(
        enabled=False,
        base_url=None,
        token=None,
        timeout_seconds=5,
    )

    with pytest.raises(ApplicationError) as error:
        await client.list_scenarios()

    assert error.value.code == "LAB_DISABLED"
    assert error.value.status_code == 404


def test_lab_configuration_is_local_only_and_complete() -> None:
    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        Settings(
            environment="production",
            lab_enabled=True,
            lab_controller_url="http://lab-controller:8010",
            lab_controller_token="token",
            alertmanager_webhook_token="alert-token",
            runner_bootstrap_token="runner-token",
            control_plane_bootstrap_token="control-token",
        )

    with pytest.raises(ValidationError, match="URL and token are required"):
        Settings(environment="test", lab_enabled=True)
