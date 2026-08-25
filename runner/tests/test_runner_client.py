import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from opspilot_runner.client import RunnerClient, RunnerCredentials
from opspilot_runner.config import RunnerSettings
from opspilot_runner.contracts import ActionResult, ExecutionResult


class SuccessfulRegistry:
    def capabilities(self) -> dict[str, list[dict[str, object]]]:
        return {"connectors": []}

    async def execute(
        self,
        connector: str,
        operation: str,
        parameters: dict[str, Any],
        timeout: int,
    ) -> ExecutionResult:
        return ExecutionResult(
            summary="done",
            output="{}",
            redacted=False,
            truncated=False,
        )

    async def execute_action(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout: int,
    ) -> ActionResult:
        return ActionResult(summary="action done")


class BlockingRegistry:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def execute(
        self,
        connector: str,
        operation: str,
        parameters: dict[str, Any],
        timeout: int,
    ) -> ExecutionResult:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_cancelled_completion_conflict_does_not_stop_runner(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "RUNNER_TASK_NOT_LEASED",
                    "message": "Runner task is not leased",
                }
            },
            request=request,
        )

    settings = RunnerSettings(
        name="runner-client-test",
        control_plane_url="http://control-plane.test/runner/v1",
        credential_file=tmp_path / "credentials.json",
    )
    client = RunnerClient(settings)
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url="http://control-plane.test/runner/v1",
        transport=httpx.MockTransport(handler),
    )
    client.credentials = RunnerCredentials(uuid4(), "test-token")
    client.registry = SuccessfulRegistry()  # type: ignore[assignment]

    await client._execute_task(
        {
            "id": str(uuid4()),
            "connector": "docker",
            "operation": "docker.container_health",
            "parameters": {"containerId": "api-01"},
            "timeoutSeconds": 30,
            "taskFencingToken": 7,
        }
    )
    await client.close()


@pytest.mark.asyncio
async def test_long_task_renews_lease_and_heartbeats(tmp_path: Path) -> None:
    calls: list[str] = []
    task_id = uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/renew"):
            return httpx.Response(
                200,
                json={"leaseExpiresAt": (datetime.now(UTC) + timedelta(seconds=10)).isoformat()},
                request=request,
            )
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"fencingToken": 12}, request=request)
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"duplicate": False}, request=request)
        raise AssertionError(f"Unexpected request: {request.url}")

    settings = RunnerSettings(
        name="runner-client-test",
        control_plane_url="http://control-plane.test/runner/v1",
        credential_file=tmp_path / "credentials.json",
    )
    settings.task_renew_seconds = 0.01
    settings.heartbeat_seconds = 0.01
    client = RunnerClient(settings)
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url="http://control-plane.test/runner/v1",
        transport=httpx.MockTransport(handler),
    )
    client.credentials = RunnerCredentials(uuid4(), "test-token")

    class DelayedRegistry(SuccessfulRegistry):
        async def execute(
            self,
            connector: str,
            operation: str,
            parameters: dict[str, Any],
            timeout: int,
        ) -> ExecutionResult:
            await asyncio.sleep(0.15)
            return await super().execute(connector, operation, parameters, timeout)

    client.registry = DelayedRegistry()  # type: ignore[assignment]
    await client._execute_task(
        {
            "id": str(task_id),
            "connector": "docker",
            "operation": "docker.container_health",
            "parameters": {"containerId": "api-01"},
            "timeoutSeconds": 30,
            "taskFencingToken": 7,
            "leaseExpiresAt": (datetime.now(UTC) + timedelta(seconds=10)).isoformat(),
        }
    )

    assert any(path.endswith("/renew") for path in calls)
    assert any(path.endswith("/heartbeat") for path in calls)
    assert calls[-1].endswith("/complete")
    await client.close()


@pytest.mark.asyncio
async def test_stale_renewal_cancels_execution_without_completion(tmp_path: Path) -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            409,
            json={"error": {"code": "TASK_LEASE_EXPIRED", "message": "expired"}},
            request=request,
        )

    settings = RunnerSettings(
        name="runner-client-test",
        control_plane_url="http://control-plane.test/runner/v1",
        credential_file=tmp_path / "credentials.json",
    )
    settings.task_renew_seconds = 0.01
    registry = BlockingRegistry()
    client = RunnerClient(settings)
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url="http://control-plane.test/runner/v1",
        transport=httpx.MockTransport(handler),
    )
    client.credentials = RunnerCredentials(uuid4(), "test-token")
    client.registry = registry  # type: ignore[assignment]

    await client._execute_task(
        {
            "id": str(uuid4()),
            "connector": "docker",
            "operation": "docker.container_health",
            "parameters": {"containerId": "api-01"},
            "timeoutSeconds": 30,
            "taskFencingToken": 7,
        }
    )

    assert registry.started.is_set()
    assert registry.cancelled.is_set()
    assert len(calls) == 1
    assert calls[0].endswith("/renew")
    await client.close()


@pytest.mark.asyncio
async def test_heartbeat_persists_rotated_access_token(tmp_path: Path) -> None:
    runner_id = uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "fencingToken": 9,
                "accessToken": "rotated-runner-token",
                "tokenExpiresAt": "2026-08-12T00:00:00Z",
            },
            request=request,
        )

    credential_file = tmp_path / "credentials.json"
    settings = RunnerSettings(
        control_plane_url="http://control-plane.test/runner/v1",
        credential_file=credential_file,
    )
    client = RunnerClient(settings)
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url=settings.control_plane_url,
        transport=httpx.MockTransport(handler),
    )
    client.credentials = RunnerCredentials(runner_id, "old-runner-token")
    client.registry = SuccessfulRegistry()  # type: ignore[assignment]

    await client._heartbeat()

    assert client.credentials.access_token == "rotated-runner-token"
    assert client.store.load() == RunnerCredentials(runner_id, "rotated-runner-token")
    await client.close()


@pytest.mark.asyncio
async def test_long_action_renews_lease_heartbeats_and_completes(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        calls.append((request.url.path, body))
        if request.url.path.endswith("/renew"):
            return httpx.Response(
                200,
                json={"leaseExpiresAt": (datetime.now(UTC) + timedelta(seconds=10)).isoformat()},
                request=request,
            )
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"fencingToken": 12}, request=request)
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"duplicate": False}, request=request)
        raise AssertionError(f"Unexpected request: {request.url}")

    class DelayedActionRegistry(SuccessfulRegistry):
        async def execute_action(
            self,
            operation: str,
            parameters: dict[str, Any],
            timeout: int,
        ) -> ActionResult:
            await asyncio.sleep(0.15)
            return ActionResult(summary="container restarted")

    settings = RunnerSettings(
        control_plane_url="http://control-plane.test/runner/v1",
        credential_file=tmp_path / "credentials.json",
    )
    settings.action_renew_seconds = 0.01
    settings.heartbeat_seconds = 0.01
    client = RunnerClient(settings)
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url=settings.control_plane_url, transport=httpx.MockTransport(handler)
    )
    client.credentials = RunnerCredentials(uuid4(), "test-token")
    client.registry = DelayedActionRegistry()  # type: ignore[assignment]
    await client._execute_action(
        {
            "executionId": str(uuid4()),
            "capability": "container.restart",
            "parameters": {"containerId": "api"},
            "executionFencingToken": 5,
            "resourceFencingToken": 9,
            "leaseExpiresAt": (datetime.now(UTC) + timedelta(seconds=10)).isoformat(),
        }
    )

    assert any(path.endswith("/renew") for path, _ in calls)
    assert any(path.endswith("/heartbeat") for path, _ in calls)
    complete = calls[-1]
    assert complete[0].endswith("/complete")
    assert complete[1]["status"] == "succeeded"
    assert complete[1]["executionFencingToken"] == 5
    assert complete[1]["resourceFencingToken"] == 9
    assert complete[1]["completionId"]
    await client.close()


@pytest.mark.asyncio
async def test_stale_action_renewal_cancels_without_completion(tmp_path: Path) -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            409,
            json={"error": {"code": "ACTION_EXECUTION_FENCED", "message": "stale"}},
            request=request,
        )

    class BlockingActionRegistry(SuccessfulRegistry):
        def __init__(self) -> None:
            self.cancelled = asyncio.Event()

        async def execute_action(
            self,
            operation: str,
            parameters: dict[str, Any],
            timeout: int,
        ) -> ActionResult:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            raise AssertionError("unreachable")

    settings = RunnerSettings(
        control_plane_url="http://control-plane.test/runner/v1",
        credential_file=tmp_path / "credentials.json",
    )
    settings.action_renew_seconds = 0.01
    registry = BlockingActionRegistry()
    client = RunnerClient(settings)
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url=settings.control_plane_url, transport=httpx.MockTransport(handler)
    )
    client.credentials = RunnerCredentials(uuid4(), "test-token")
    client.registry = registry  # type: ignore[assignment]
    await client._execute_action(
        {
            "executionId": str(uuid4()),
            "capability": "container.restart",
            "parameters": {"containerId": "api"},
            "executionFencingToken": 5,
            "resourceFencingToken": 9,
        }
    )

    assert registry.cancelled.is_set()
    assert len(calls) == 1
    assert calls[0].endswith("/renew")
    await client.close()


@pytest.mark.asyncio
async def test_action_completion_retry_reuses_completion_id(tmp_path: Path) -> None:
    completion_ids: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        completion_ids.append(body["completionId"])
        return httpx.Response(
            500 if len(completion_ids) == 1 else 200,
            json={"duplicate": len(completion_ids) > 1},
            request=request,
        )

    settings = RunnerSettings(
        control_plane_url="http://control-plane.test/runner/v1",
        credential_file=tmp_path / "credentials.json",
    )
    client = RunnerClient(settings)
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url=settings.control_plane_url, transport=httpx.MockTransport(handler)
    )
    client.credentials = RunnerCredentials(uuid4(), "test-token")
    completion_id = str(uuid4())
    await client._complete_action(uuid4(), {"completionId": completion_id})

    assert completion_ids == [completion_id, completion_id]
    await client.close()
