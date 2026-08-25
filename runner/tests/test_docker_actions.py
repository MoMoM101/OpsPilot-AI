from collections.abc import Sequence

import pytest

from opspilot_runner.config import RunnerSettings
from opspilot_runner.connectors.docker_actions import (
    DockerActionConnector,
    DockerActionError,
)
from opspilot_runner.registry import ConnectorRegistry


class FakeDockerActionConnector(DockerActionConnector):
    def __init__(self, stdout: str = "") -> None:
        super().__init__()
        self.stdout = stdout
        self.arguments: list[str] = []

    async def _run(self, arguments: Sequence[str], timeout_seconds: int) -> str:
        self.arguments = list(arguments)
        return self.stdout


@pytest.mark.asyncio
async def test_restart_uses_fixed_argument_vector_without_shell() -> None:
    connector = FakeDockerActionConnector()

    result = await connector.execute_action("container.restart", {"containerId": "api-01"}, 30)

    assert connector.arguments == ["container", "restart", "--time", "10", "api-01"]
    assert result.summary == "Container api-01 restart request completed"


@pytest.mark.asyncio
async def test_restart_rejects_option_injection_and_extra_parameters() -> None:
    connector = FakeDockerActionConnector()

    with pytest.raises(DockerActionError) as option_error:
        await connector.execute_action("container.restart", {"containerId": "--all"}, 30)
    assert option_error.value.code == "INVALID_ACTION_TARGET"

    with pytest.raises(DockerActionError) as extra_error:
        await connector.execute_action(
            "container.restart", {"containerId": "api", "command": "sh"}, 30
        )
    assert extra_error.value.code == "INVALID_ACTION_PARAMETERS"


@pytest.mark.asyncio
async def test_health_check_accepts_running_and_rejects_unhealthy() -> None:
    healthy = FakeDockerActionConnector('{"Status":"running","Health":{"Status":"healthy"}}')
    result = await healthy.execute_action("health.check", {"target": "api"}, 30)
    assert "health=healthy" in result.summary

    unhealthy = FakeDockerActionConnector('{"Status":"running","Health":{"Status":"unhealthy"}}')
    with pytest.raises(DockerActionError) as error:
        await unhealthy.execute_action("health.check", {"target": "api"}, 30)
    assert error.value.code == "HEALTH_CHECK_FAILED"


def test_action_capabilities_are_explicit() -> None:
    assert DockerActionConnector().action_operations == ("container.restart", "health.check")
    docker = next(
        capability
        for capability in ConnectorRegistry(RunnerSettings()).capabilities()
        if capability["connector"] == "docker"
    )
    assert docker["actions"] == ["container.restart", "health.check"]
