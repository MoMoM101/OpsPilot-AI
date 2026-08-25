import asyncio
import contextlib
import json

import httpx
import pytest

from opspilot_runner.config import RunnerSettings
from opspilot_runner.connectors.http_probe import HttpProbeConnector, HttpProbeError
from opspilot_runner.connectors.tcp_probe import TcpProbeConnector, TcpProbeError
from opspilot_runner.registry import ConnectorRegistry
from opspilot_runner.target_policy import ProbeTargetPolicy, TargetPolicyError


def test_probe_policy_requires_allowlisted_host_and_port() -> None:
    policy = ProbeTargetPolicy(["localhost", "*.internal.example"], [80, 8000])

    assert policy.validate("LOCALHOST.", 8000) == "localhost"
    assert policy.validate("api.internal.example", 80) == "api.internal.example"
    with pytest.raises(TargetPolicyError):
        policy.validate("internal.example", 80)
    with pytest.raises(TargetPolicyError):
        policy.validate("localhost", 22)
    with pytest.raises(TargetPolicyError):
        policy.validate("evilinternal.example", 80)


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",
        "169.254.170.2",
        "::ffff:169.254.169.254",
        "fe80::1",
        "metadata.google.internal",
        "instance-data",
    ],
)
def test_probe_policy_always_rejects_cloud_metadata_and_link_local_targets(
    host: str,
) -> None:
    policy = ProbeTargetPolicy([host], [80])

    with pytest.raises(TargetPolicyError, match=r"metadata|link-local"):
        policy.validate(host, 80)


@pytest.mark.asyncio
async def test_http_probe_does_not_follow_redirect_and_redacts_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "localhost"
        return httpx.Response(
            302,
            headers={"Location": "http://not-allowed.example/", "Content-Type": "text/plain"},
            content="token=unsafe-value",
        )

    connector = HttpProbeConnector(
        ProbeTargetPolicy(["localhost"], [8000]),
        transport=httpx.MockTransport(handler),
    )
    result = await connector.execute(
        "http.probe",
        {
            "url": "http://localhost:8000/health",
            "expectedStatuses": [200, 302],
            "captureBody": True,
        },
        10,
    )
    payload = json.loads(result.output)

    assert payload["statusCode"] == 302
    assert payload["healthy"] is True
    assert payload["redirectLocationPresent"] is True
    assert "not-allowed.example" not in result.output
    assert "unsafe-value" not in result.output
    assert result.redacted is True


def test_http_probe_rejects_credentials_query_and_non_allowlisted_target() -> None:
    connector = HttpProbeConnector(ProbeTargetPolicy(["localhost"], [8000]))

    for url in (
        "http://user:pass@localhost:8000/health",
        "http://localhost:8000/health?token=unsafe",
        "http://localhost:8000/health#@169.254.169.254",
        "http://example.com:8000/health",
        "http://localhost:8000@169.254.169.254/latest/meta-data",
        "http://[::ffff:127.0.0.1]:8000/health",
        "gopher://localhost:8000/_unsafe",
    ):
        with pytest.raises(HttpProbeError):
            connector._validate("http.probe", {"url": url})


@pytest.mark.asyncio
async def test_tcp_probe_connects_without_sending_data() -> None:
    received = bytearray()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(TimeoutError):
            received.extend(await asyncio.wait_for(reader.read(1), timeout=0.05))
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    socket = server.sockets[0]
    port = int(socket.getsockname()[1])
    connector = TcpProbeConnector(ProbeTargetPolicy(["127.0.0.1"], [port]))
    try:
        result = await connector.execute(
            "tcp.probe",
            {"host": "127.0.0.1", "port": port},
            10,
        )
    finally:
        server.close()
        await server.wait_closed()

    assert json.loads(result.output)["reachable"] is True
    assert received == b""


def test_tcp_probe_rejects_non_allowlisted_port() -> None:
    connector = TcpProbeConnector(ProbeTargetPolicy(["127.0.0.1"], [443]))

    with pytest.raises(TcpProbeError) as error:
        connector._validate(
            "tcp.probe",
            {"host": "127.0.0.1", "port": 22},
        )

    assert error.value.code == "TCP_TARGET_NOT_ALLOWED"


def test_registry_advertises_probes_only_with_complete_allowlist() -> None:
    disabled = ConnectorRegistry(RunnerSettings(probe_allowed_hosts=["localhost"]))
    enabled = ConnectorRegistry(
        RunnerSettings(
            probe_allowed_hosts=["localhost"],
            probe_allowed_ports=[80, 443],
        )
    )

    assert "http" not in {item["connector"] for item in disabled.capabilities()}
    assert {"http", "tcp"} <= {item["connector"] for item in enabled.capabilities()}
