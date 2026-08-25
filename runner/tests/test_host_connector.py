import json
from pathlib import Path

import pytest

from opspilot_runner.connectors.host import HostSnapshotConnector


@pytest.mark.asyncio
async def test_host_snapshot_collects_bounded_non_secret_fields() -> None:
    result = await HostSnapshotConnector().execute("host.snapshot", {}, 10)
    payload = json.loads(result.output)

    assert payload["schemaVersion"] == "1.0"
    assert payload["platform"]["system"]
    assert "logicalCount" in payload["cpu"]
    assert payload["disk"]["totalBytes"] >= payload["disk"]["freeBytes"]
    lowered = result.output.lower()
    assert "commandline" not in lowered
    assert "environment" not in lowered
    assert "macaddress" not in lowered
    assert "ipaddress" not in lowered
    if payload["platform"]["system"] != "Linux":
        assert "processCount" not in payload
        assert "network" not in payload


def test_linux_memory_parser_uses_available_memory(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       1000 kB\nMemAvailable:    250 kB\nMemFree: 100 kB\n",
        encoding="utf-8",
    )

    result = HostSnapshotConnector._linux_memory(meminfo)

    assert result == {
        "totalBytes": 1024000,
        "availableBytes": 256000,
        "usedBytes": 768000,
        "usedPercent": 75.0,
    }


def test_linux_network_parser_returns_only_counters(tmp_path: Path) -> None:
    netdev = tmp_path / "netdev"
    netdev.write_text(
        "Inter-| Receive | Transmit\n"
        " face |bytes packets errs drop fifo frame compressed multicast|"
        "bytes packets errs drop fifo colls carrier compressed\n"
        " eth0: 100 2 0 0 0 0 0 0 300 4 0 0 0 0 0 0\n",
        encoding="utf-8",
    )

    assert HostSnapshotConnector._linux_network(netdev) == [
        {
            "interface": "eth0",
            "receiveBytes": 100,
            "receivePackets": 2,
            "transmitBytes": 300,
            "transmitPackets": 4,
        }
    ]
