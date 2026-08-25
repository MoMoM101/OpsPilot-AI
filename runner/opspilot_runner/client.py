import asyncio
import contextlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

from opspilot_runner import __version__
from opspilot_runner.config import RunnerSettings
from opspilot_runner.contracts import ConnectorError
from opspilot_runner.registry import ConnectorRegistry

_STALE_TASK_CODES = {
    "RUNNER_TASK_NOT_LEASED",
    "STALE_TASK_FENCING_TOKEN",
    "TASK_LEASE_EXPIRED",
}
_STALE_ACTION_CODES = {
    "ACTION_EXECUTION_FENCED",
    "ACTION_NOT_RUNNING",
    "ACTION_EXECUTION_LEASE_EXPIRED",
    "ACTION_RESOURCE_LOCK_INVALID",
}


@dataclass(frozen=True, slots=True)
class RunnerCredentials:
    runner_id: UUID
    access_token: str


class CredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RunnerCredentials | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return RunnerCredentials(
            runner_id=UUID(str(payload["runnerId"])),
            access_token=str(payload["accessToken"]),
        )

    def save(self, credentials: RunnerCredentials) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "runnerId": str(credentials.runner_id),
                    "accessToken": credentials.access_token,
                }
            ),
            encoding="utf-8",
        )
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(self.path)


class RunnerClient:
    def __init__(self, settings: RunnerSettings) -> None:
        self.settings = settings
        self.store = CredentialStore(settings.credential_file)
        self.registry = ConnectorRegistry(settings)
        self.http = httpx.AsyncClient(
            base_url=settings.control_plane_url.rstrip("/"),
            timeout=30,
        )
        self.credentials: RunnerCredentials | None = None
        self.fencing_token: int | None = None

    async def close(self) -> None:
        await self.http.aclose()

    async def run_forever(self) -> None:
        self.credentials = self.store.load()
        if self.credentials is None:
            await self._register()
        await self._heartbeat()
        next_heartbeat = time.monotonic() + self.settings.heartbeat_seconds
        while True:
            if time.monotonic() >= next_heartbeat:
                await self._heartbeat()
                next_heartbeat = time.monotonic() + self.settings.heartbeat_seconds
            action = await self._claim_action()
            if action is not None:
                await self._execute_action(action)
                next_heartbeat = time.monotonic() + self.settings.heartbeat_seconds
                continue
            task = await self._claim()
            if task is None:
                await asyncio.sleep(self.settings.poll_seconds)
                continue
            await self._execute_task(task)

    async def _register(self) -> None:
        headers: dict[str, str] = {}
        if self.settings.bootstrap_token:
            headers["X-OpsPilot-Runner-Bootstrap-Token"] = self.settings.bootstrap_token
        payload: dict[str, Any] = {
            "name": self.settings.name,
            "softwareVersion": __version__,
            "capabilities": self.registry.capabilities(),
            "labels": {"platform": sys.platform},
        }
        if self.settings.environment_id:
            payload["environmentId"] = str(self.settings.environment_id)
        response = await self.http.post("/runners/register", json=payload, headers=headers)
        self._raise_for_status(response)
        body = response.json()
        self.credentials = RunnerCredentials(
            runner_id=UUID(body["id"]),
            access_token=body["accessToken"],
        )
        self.fencing_token = int(body["fencingToken"])
        self.store.save(self.credentials)

    async def _heartbeat(self) -> None:
        credentials = self._credentials()
        response = await self.http.post(
            f"/runners/{credentials.runner_id}/heartbeat",
            json={
                "heartbeatId": str(uuid4()),
                "softwareVersion": __version__,
                "capabilities": self.registry.capabilities(),
                "labels": {"platform": sys.platform},
            },
            headers=self._authorization(),
        )
        self._raise_for_status(response)
        body = response.json()
        self.fencing_token = int(body["fencingToken"])
        rotated_token = body.get("accessToken")
        if isinstance(rotated_token, str) and rotated_token:
            current = self._credentials()
            rotated = RunnerCredentials(current.runner_id, rotated_token)
            self.store.save(rotated)
            self.credentials = rotated

    async def _claim(self) -> dict[str, Any] | None:
        if self.fencing_token is None:
            raise RuntimeError("Runner has no fencing token")
        credentials = self._credentials()
        response = await self.http.post(
            f"/runners/{credentials.runner_id}/tasks/claim",
            json={"runnerFencingToken": self.fencing_token},
            headers=self._authorization(),
        )
        self._raise_for_status(response)
        task = response.json()["task"]
        return task if isinstance(task, dict) else None

    async def _claim_action(self) -> dict[str, Any] | None:
        if self.fencing_token is None:
            raise RuntimeError("Runner has no fencing token")
        credentials = self._credentials()
        response = await self.http.post(
            f"/runners/{credentials.runner_id}/actions/claim",
            json={"runnerFencingToken": self.fencing_token},
            headers=self._authorization(),
        )
        self._raise_for_status(response)
        execution = response.json()["execution"]
        return execution if isinstance(execution, dict) else None

    async def _execute_task(self, task: dict[str, Any]) -> None:
        task_id = UUID(str(task["id"]))
        fencing_token = int(task["taskFencingToken"])
        timeout = min(int(task["timeoutSeconds"]), self.settings.docker_timeout_seconds)
        execution = asyncio.create_task(self._connector_payload(task, fencing_token, timeout))
        next_heartbeat = time.monotonic() + self.settings.heartbeat_seconds
        next_renew = time.monotonic() + self._renew_interval(
            task.get("leaseExpiresAt"), self.settings.task_renew_seconds
        )
        try:
            while not execution.done():
                deadline = min(next_heartbeat, next_renew)
                done, _ = await asyncio.wait(
                    {execution},
                    timeout=max(0.0, deadline - time.monotonic()),
                )
                if done:
                    break
                now = time.monotonic()
                if now >= next_renew:
                    lease_expires_at = await self._renew_task(task_id, fencing_token)
                    if lease_expires_at is None:
                        await self._cancel_execution(execution)
                        return
                    next_renew = time.monotonic() + self._renew_interval(
                        lease_expires_at, self.settings.task_renew_seconds
                    )
                if now >= next_heartbeat:
                    await self._heartbeat()
                    next_heartbeat = time.monotonic() + self.settings.heartbeat_seconds
            payload = await execution
        except BaseException:
            await self._cancel_execution(execution)
            raise

        credentials = self._credentials()
        response = await self.http.post(
            f"/runners/{credentials.runner_id}/tasks/{task_id}/complete",
            json=payload,
            headers=self._authorization(),
        )
        if response.status_code == 409 and self._error_code(response) in _STALE_TASK_CODES:
            return
        self._raise_for_status(response)

    async def _connector_payload(
        self,
        task: dict[str, Any],
        fencing_token: int,
        timeout: int,
    ) -> dict[str, Any]:
        try:
            result = await self.registry.execute(
                str(task["connector"]),
                str(task["operation"]),
                dict(task.get("parameters", {})),
                timeout,
            )
            return {
                "completionId": str(uuid4()),
                "taskFencingToken": fencing_token,
                "status": "succeeded",
                "summary": result.summary,
                "output": result.output,
                "redacted": result.redacted,
                "outputTruncated": result.truncated,
            }
        except ConnectorError as exc:
            return {
                "completionId": str(uuid4()),
                "taskFencingToken": fencing_token,
                "status": "failed",
                "summary": str(exc)[:1000] or "Read-only connector query failed",
                "errorCode": exc.code,
            }
        except Exception:
            return {
                "completionId": str(uuid4()),
                "taskFencingToken": fencing_token,
                "status": "failed",
                "summary": "Connector failed without exposing internal details",
                "errorCode": "CONNECTOR_INTERNAL_ERROR",
            }

    async def _renew_task(self, task_id: UUID, fencing_token: int) -> str | None:
        credentials = self._credentials()
        response = await self.http.post(
            f"/runners/{credentials.runner_id}/tasks/{task_id}/renew",
            json={"taskFencingToken": fencing_token},
            headers=self._authorization(),
        )
        if response.status_code == 409 and self._error_code(response) in _STALE_TASK_CODES:
            return None
        self._raise_for_status(response)
        lease_expires_at = response.json().get("leaseExpiresAt")
        return str(lease_expires_at) if lease_expires_at else None

    async def _execute_action(self, action: dict[str, Any]) -> None:
        execution_id = UUID(str(action["executionId"]))
        execution_token = int(action["executionFencingToken"])
        resource_token = int(action["resourceFencingToken"])
        execution = asyncio.create_task(self._action_payload(action))
        next_heartbeat = time.monotonic() + self.settings.heartbeat_seconds
        next_renew = time.monotonic() + self._renew_interval(
            action.get("leaseExpiresAt"), self.settings.action_renew_seconds
        )
        try:
            while not execution.done():
                deadline = min(next_heartbeat, next_renew)
                done, _ = await asyncio.wait(
                    {execution}, timeout=max(0.0, deadline - time.monotonic())
                )
                if done:
                    break
                now = time.monotonic()
                if now >= next_renew:
                    lease_expires_at = await self._renew_action(
                        execution_id, execution_token, resource_token
                    )
                    if lease_expires_at is None:
                        await self._cancel_action(execution)
                        return
                    next_renew = time.monotonic() + self._renew_interval(
                        lease_expires_at, self.settings.action_renew_seconds
                    )
                if now >= next_heartbeat:
                    await self._heartbeat()
                    next_heartbeat = time.monotonic() + self.settings.heartbeat_seconds
            payload = await execution
        except BaseException:
            await self._cancel_action(execution)
            raise
        payload.update(
            {
                "completionId": str(uuid4()),
                "executionFencingToken": execution_token,
                "resourceFencingToken": resource_token,
            }
        )
        await self._complete_action(execution_id, payload)

    async def _action_payload(self, action: dict[str, Any]) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self.settings.action_timeout_seconds):
                result = await self.registry.execute_action(
                    str(action["capability"]),
                    dict(action.get("parameters", {})),
                    self.settings.action_timeout_seconds,
                )
            return {"status": "succeeded", "summary": result.summary}
        except TimeoutError:
            return {
                "status": "failed",
                "summary": "Action execution timed out",
                "errorCode": "ACTION_TIMEOUT",
            }
        except ConnectorError as exc:
            return {
                "status": "failed",
                "summary": str(exc)[:2000] or "Action execution failed",
                "errorCode": exc.code,
            }
        except Exception:
            return {
                "status": "failed",
                "summary": "Action failed without exposing internal details",
                "errorCode": "ACTION_INTERNAL_ERROR",
            }

    async def _renew_action(
        self, execution_id: UUID, execution_token: int, resource_token: int
    ) -> str | None:
        credentials = self._credentials()
        response = await self.http.post(
            f"/runners/{credentials.runner_id}/actions/{execution_id}/renew",
            json={
                "executionFencingToken": execution_token,
                "resourceFencingToken": resource_token,
            },
            headers=self._authorization(),
        )
        if response.status_code == 409 and self._error_code(response) in _STALE_ACTION_CODES:
            return None
        self._raise_for_status(response)
        lease_expires_at = response.json().get("leaseExpiresAt")
        return str(lease_expires_at) if lease_expires_at else None

    async def _complete_action(self, execution_id: UUID, payload: dict[str, Any]) -> None:
        credentials = self._credentials()
        for attempt in range(3):
            try:
                response = await self.http.post(
                    f"/runners/{credentials.runner_id}/actions/{execution_id}/complete",
                    json=payload,
                    headers=self._authorization(),
                )
            except httpx.TransportError:
                if attempt == 2:
                    raise
            else:
                if (
                    response.status_code == 409
                    and self._error_code(response) in _STALE_ACTION_CODES
                ):
                    return
                if response.status_code < 500 or attempt == 2:
                    self._raise_for_status(response)
                    return
            await asyncio.sleep(0.25 * (2**attempt))

    def _renew_interval(self, lease_expires_at: object, configured: float) -> float:
        if not isinstance(lease_expires_at, str):
            return configured
        try:
            expires_at = datetime.fromisoformat(lease_expires_at.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                return configured
            remaining = (expires_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        except ValueError:
            return configured
        return max(0.1, min(configured, remaining / 3))

    @staticmethod
    async def _cancel_execution(execution: asyncio.Task[dict[str, Any]]) -> None:
        if execution.done():
            return
        execution.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await execution

    @staticmethod
    async def _cancel_action(execution: asyncio.Task[dict[str, Any]]) -> None:
        if execution.done():
            return
        execution.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await execution

    def _credentials(self) -> RunnerCredentials:
        if self.credentials is None:
            raise RuntimeError("Runner is not registered")
        return self.credentials

    def _authorization(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._credentials().access_token}"}

    @staticmethod
    def _error_code(response: httpx.Response) -> str:
        try:
            error = response.json().get("error", {})
            return str(error.get("code", "CONTROL_PLANE_ERROR"))
        except (ValueError, AttributeError):
            return "CONTROL_PLANE_ERROR"

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            error = response.json().get("error", {})
            message = error.get("message", f"HTTP {response.status_code}")
            code = error.get("code", "CONTROL_PLANE_ERROR")
        except (ValueError, AttributeError):
            message = f"HTTP {response.status_code}"
            code = "CONTROL_PLANE_ERROR"
        raise RuntimeError(f"{code}: {message}")
