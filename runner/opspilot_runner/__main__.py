import argparse
import asyncio
import json
import sys
from typing import Any
from urllib.parse import urlsplit

import httpx

from opspilot_runner.client import CredentialStore, RunnerClient
from opspilot_runner.config import RunnerSettings
from opspilot_runner.connectors.docker import DockerReadOnlyConnector
from opspilot_runner.connectors.host import HostSnapshotConnector


async def _serve() -> None:
    client = RunnerClient(RunnerSettings())
    try:
        await client.run_forever()
    finally:
        await client.close()


async def _docker_list() -> None:
    settings = RunnerSettings()
    connector = DockerReadOnlyConnector(max_output_bytes=settings.max_output_bytes)
    result = await connector.execute(
        "docker.list_containers",
        {},
        settings.docker_timeout_seconds,
    )
    print(json.dumps({"summary": result.summary, "output": result.output}, ensure_ascii=False))


async def _host_snapshot() -> None:
    settings = RunnerSettings()
    result = await HostSnapshotConnector(max_output_bytes=settings.max_output_bytes).execute(
        "host.snapshot", {}, 30
    )
    print(json.dumps({"summary": result.summary, "output": result.output}, ensure_ascii=False))


async def _healthcheck() -> None:
    settings = RunnerSettings()
    if CredentialStore(settings.credential_file).load() is None:
        raise RuntimeError("Runner credentials are not initialized")
    control_plane = urlsplit(settings.control_plane_url)
    health_url = f"{control_plane.scheme}://{control_plane.netloc}/api/v1/health"
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(health_url)
        response.raise_for_status()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpsPilot read-only Runner")
    parser.add_argument(
        "command",
        choices=("serve", "docker-list", "host-snapshot", "healthcheck"),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    arguments: dict[str, Any] = vars(_parser().parse_args(argv))
    if arguments["command"] == "serve":
        asyncio.run(_serve())
    elif arguments["command"] == "docker-list":
        asyncio.run(_docker_list())
    elif arguments["command"] == "host-snapshot":
        asyncio.run(_host_snapshot())
    else:
        try:
            asyncio.run(_healthcheck())
        except Exception as exc:
            print(f"Runner healthcheck failed: {type(exc).__name__}", file=sys.stderr)
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
