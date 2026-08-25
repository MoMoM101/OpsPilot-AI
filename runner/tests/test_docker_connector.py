import json
from collections.abc import Sequence
from typing import Any

import pytest

from opspilot_runner.connectors.docker import DockerConnectorError, DockerReadOnlyConnector


class FakeDockerConnector(DockerReadOnlyConnector):
    async def _run(self, arguments: Sequence[str], timeout_seconds: int) -> tuple[str, str]:
        return "token=unsafe-value\n" + ("x" * 2000), ""


def test_docker_connector_exposes_only_read_operations() -> None:
    connector = DockerReadOnlyConnector()

    assert set(connector.observe_operations) == {
        "docker.list_containers",
        "docker.inspect_container",
        "docker.container_logs",
        "docker.container_health",
    }
    assert all("restart" not in operation for operation in connector.observe_operations)


def test_docker_connector_rejects_option_injection_and_unknown_parameters() -> None:
    connector = DockerReadOnlyConnector()

    with pytest.raises(DockerConnectorError) as option_error:
        connector._arguments(
            "docker.container_logs",
            {"containerId": "--all", "tail": 10},
        )
    assert option_error.value.code == "INVALID_CONTAINER_ID"

    with pytest.raises(DockerConnectorError) as parameter_error:
        connector._arguments(
            "docker.container_logs",
            {"containerId": "api-01", "follow": True},
        )
    assert parameter_error.value.code == "INVALID_DOCKER_PARAMETERS"


@pytest.mark.asyncio
async def test_docker_connector_redacts_and_truncates_locally() -> None:
    connector = FakeDockerConnector(max_output_bytes=1024)

    result = await connector.execute(
        "docker.container_logs",
        {"containerId": "api-01"},
        10,
    )

    assert result.redacted is True
    assert result.truncated is True
    assert "unsafe-value" not in result.output
    assert len(result.output.encode()) <= 1024


def test_docker_inspect_drops_environment_labels_and_host_paths() -> None:
    raw = {
        "Id": "abc",
        "Name": "/api",
        "Config": {
            "Image": "api:latest",
            "Env": ["PASSWORD=unsafe"],
            "Labels": {"secret": "unsafe"},
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "C:/private/source",
                "Destination": "/data",
                "RW": False,
            }
        ],
        "State": {"Status": "running", "Pid": 100},
    }

    normalized = DockerReadOnlyConnector._normalize_output(
        "docker.inspect_container",
        json.dumps(raw),
    )

    assert "PASSWORD" not in normalized
    assert "Labels" not in normalized
    assert "private/source" not in normalized
    assert '"Destination":"/data"' in normalized


@pytest.mark.parametrize(
    ("parameters", "expected_tail"),
    [
        ({"containerId": "api-01"}, "200"),
        ({"containerId": "api-01", "tail": 1}, "1"),
        ({"containerId": "api-01", "tail": 2000}, "2000"),
    ],
)
def test_docker_log_tail_is_bounded(
    parameters: dict[str, Any],
    expected_tail: str,
) -> None:
    arguments = DockerReadOnlyConnector()._arguments(
        "docker.container_logs",
        parameters,
    )

    assert arguments[arguments.index("--tail") + 1] == expected_tail


def test_docker_connector_rejects_write_operation() -> None:
    with pytest.raises(DockerConnectorError) as error:
        DockerReadOnlyConnector()._arguments(
            "docker.restart_container",
            {"containerId": "api-01"},
        )

    assert error.value.code == "UNSUPPORTED_DOCKER_OPERATION"
