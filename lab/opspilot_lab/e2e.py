import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from opspilot_lab.scenarios import SCENARIOS, RagExpectation, ScenarioManifest


class E2ESettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSPILOT_LAB_E2E_", extra="ignore")

    control_plane_url: str = "http://127.0.0.1:8000/api/v1"
    access_token: str = ""
    access_token_file: Path | None = None
    alertmanager_webhook_token: str = ""
    alertmanager_webhook_token_file: Path | None = None
    rag_url: str = "http://127.0.0.1:18000"
    timeout_seconds: float = 10
    recovery_attempts: int = 20
    recovery_interval_seconds: float = 0.5

    @model_validator(mode="after")
    def load_secret_files(self) -> "E2ESettings":
        if self.access_token_file is not None:
            self.access_token = self._secret(self.access_token_file, "Admin access token")
        if self.alertmanager_webhook_token_file is not None:
            self.alertmanager_webhook_token = self._secret(
                self.alertmanager_webhook_token_file,
                "Alertmanager webhook token",
            )
        return self

    @staticmethod
    def _secret(path: Path, name: str) -> str:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"Unable to read {name} file") from exc
        if not value or len(value.encode()) > 16384:
            raise ValueError(f"{name} file must contain 1 to 16384 bytes")
        return value


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    degraded_status: int
    recovered_status: int
    recovered_point_count: int | None
    incident_id: str
    investigation_run_id: str
    evidence_id: str
    observation_operation: str
    audit_asserted: bool


class ScenarioVerifier:
    def __init__(
        self,
        settings: E2ESettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.access_token:
            raise ValueError("OPSPILOT_LAB_E2E_ACCESS_TOKEN is required")
        if not settings.alertmanager_webhook_token:
            raise ValueError("OPSPILOT_LAB_E2E_ALERTMANAGER_WEBHOOK_TOKEN is required")
        self.settings = settings
        self.transport = transport

    async def run(self, manifest: ScenarioManifest) -> ScenarioResult:
        resource = await self._ensure_resource(manifest)
        cleanup_key = self._key(manifest.id, "cleanup-before")
        await self._mutate(manifest.id, "cleanup", cleanup_key)
        await self._wait_for(manifest.recovered_rag)
        inject_path = f"/lab/scenarios/{manifest.id}/inject"
        try:
            await self._mutate(manifest.id, "inject", self._key(manifest.id, "inject"))
            degraded = await self._wait_for(manifest.degraded_rag)
            incident_id = await self._send_and_assert_alert(manifest, resource)
            await self._assert_audit(inject_path)
            run_id, evidence_id, operation = await self._run_investigation(
                manifest,
                incident_id,
            )
        finally:
            await self._mutate(
                manifest.id,
                "cleanup",
                self._key(manifest.id, "cleanup-after"),
            )
        recovered = await self._wait_for(manifest.recovered_rag)
        await self._assert_audit(f"/lab/scenarios/{manifest.id}/cleanup")
        return ScenarioResult(
            scenario_id=manifest.id,
            degraded_status=degraded.status_code,
            recovered_status=recovered.status_code,
            recovered_point_count=self._point_count(recovered),
            incident_id=incident_id,
            investigation_run_id=run_id,
            evidence_id=evidence_id,
            observation_operation=operation,
            audit_asserted=True,
        )

    async def _ensure_resource(self, manifest: ScenarioManifest) -> dict[str, Any]:
        resource_name = f"rag-lab-{manifest.id}"
        environments = (await self._control("GET", "/environments?limit=100")).json()
        environment = next(
            (item for item in environments if item.get("slug") == "fault-lab"),
            None,
        )
        if environment is None:
            environment = (
                await self._control(
                    "POST",
                    "/environments",
                    {"name": "Fault Lab", "slug": "fault-lab"},
                )
            ).json()
        resources = (await self._control("GET", "/resources?limit=100")).json()
        resource = next(
            (
                item
                for item in resources
                if item.get("environmentId") == environment["id"]
                and item.get("name") == resource_name
            ),
            None,
        )
        if resource is not None:
            return cast(dict[str, Any], resource)
        return cast(
            dict[str, Any],
            (
                await self._control(
                    "POST",
                    "/resources",
                    {
                        "environmentId": environment["id"],
                        "name": resource_name,
                        "kind": "rag",
                        "criticality": "high",
                        "attributes": {"observability": {"runnerOperations": self._operations()}},
                    },
                )
            ).json(),
        )

    async def _send_and_assert_alert(
        self,
        manifest: ScenarioManifest,
        resource: dict[str, Any],
    ) -> str:
        fingerprint = f"lab-{manifest.id}-{uuid4()}"
        occurred_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        response = await self._control(
            "POST",
            "/alerts/webhook/alertmanager",
            {
                "version": "4",
                "status": "firing",
                "receiver": "opspilot-lab",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {
                            "alertname": manifest.expected_alerts[0],
                            "instance": resource["name"],
                            "severity": "high",
                        },
                        "annotations": {"summary": manifest.background},
                        "startsAt": occurred_at,
                        "fingerprint": fingerprint,
                    }
                ],
            },
            public=True,
        )
        ingestion = response.json()
        if ingestion.get("unmatched") != 0:
            raise AssertionError(f"Lab alert did not match its Resource: {ingestion}")
        alerts = (
            await self._control(
                "GET",
                f"/alerts?resource_id={resource['id']}&limit=100",
            )
        ).json()
        alert = next((item for item in alerts if item.get("fingerprint") == fingerprint), None)
        if alert is None or not alert.get("incidentId"):
            raise AssertionError("Lab alert was not persisted and correlated to an Incident")
        return str(alert["incidentId"])

    async def _assert_audit(self, path: str) -> None:
        records = (await self._control("GET", "/audit-logs?limit=500")).json()
        if not any(
            record.get("method") == "POST"
            and record.get("path") == f"/api/v1{path}"
            and record.get("outcome") == "success"
            for record in records
        ):
            raise AssertionError(f"No successful audit record found for {path}")

    async def _run_investigation(
        self,
        manifest: ScenarioManifest,
        incident_id: str,
    ) -> tuple[str, str, str]:
        await self._ensure_incident_investigating(incident_id)
        run = (
            await self._control(
                "POST",
                f"/incidents/{incident_id}/investigation-runs",
                {
                    "idempotencyKey": self._key(manifest.id, "investigation"),
                    "graphVersion": "graph-v1",
                    "maxIterations": 3,
                    "maxModelRequests": 10,
                },
            )
        ).json()
        run_id = str(run["id"])
        final_run: dict[str, Any] | None = None
        for attempt in range(self.settings.recovery_attempts):
            candidate = (await self._control("GET", f"/investigation-runs/{run_id}")).json()
            if candidate.get("status") in {"completed", "failed", "cancelled"}:
                final_run = candidate
                break
            if attempt + 1 < self.settings.recovery_attempts:
                await asyncio.sleep(self.settings.recovery_interval_seconds)
        if final_run is None or final_run.get("status") != "completed":
            raise AssertionError(f"Lab Investigation did not complete: {final_run or run}")

        tasks = (
            await self._control(
                "GET",
                f"/runner-tasks?incident_id={incident_id}&limit=100",
            )
        ).json()
        task = next(
            (
                item
                for item in tasks
                if item.get("operation") in manifest.expected_investigation
                and item.get("evidenceId")
                and item.get("status") in {"succeeded", "failed"}
            ),
            None,
        )
        if task is None:
            raise AssertionError("Lab Investigation produced no expected RunnerTask Evidence")
        evidence_id = str(task["evidenceId"])
        evidence = (await self._control("GET", f"/evidence/{evidence_id}")).json()
        if evidence.get("incidentId") != incident_id:
            raise AssertionError("Lab Evidence is not bound to the correlated Incident")
        if evidence.get("collectionStatus") not in {"succeeded", "failed"}:
            raise AssertionError(f"Lab Evidence has invalid collection status: {evidence}")
        return run_id, evidence_id, str(task["operation"])

    async def _ensure_incident_investigating(self, incident_id: str) -> None:
        incident = (await self._control("GET", f"/incidents/{incident_id}")).json()
        while incident.get("status") != "INVESTIGATING":
            current = incident.get("status")
            target = {"DETECTED": "CORRELATING", "CORRELATING": "INVESTIGATING"}.get(current)
            if target is None:
                raise AssertionError(f"Lab Incident cannot enter investigation from {current}")
            incident = (
                await self._control(
                    "POST",
                    f"/incidents/{incident_id}/transitions",
                    {"target": target, "expectedVersion": incident["version"]},
                )
            ).json()

    async def _mutate(self, scenario_id: str, action: str, key: str) -> None:
        response = await self._control(
            "POST",
            f"/lab/scenarios/{scenario_id}/{action}",
            {"idempotencyKey": key},
        )
        response.raise_for_status()

    async def _control(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        public: bool = False,
    ) -> httpx.Response:
        headers = (
            {"X-OpsPilot-Webhook-Token": self.settings.alertmanager_webhook_token}
            if public
            else {"Authorization": f"Bearer {self.settings.access_token}"}
        )
        async with httpx.AsyncClient(
            base_url=self.settings.control_plane_url.rstrip("/"),
            transport=self.transport,
            timeout=self.settings.timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.request(method, path, json=body, headers=headers)
        response.raise_for_status()
        return response

    @staticmethod
    def _operations() -> dict[str, Any]:
        return {
            "sqlite.health": {"parameters": {"path": "/lab/data/rag.db"}},
            "sqlite.lock_status": {"parameters": {"path": "/lab/data/rag.db"}},
            "sqlite.integrity_check": {"parameters": {"path": "/lab/data/rag.db"}},
            "qdrant.health": {"parameters": {"baseUrl": "http://toxiproxy:16333"}},
            "qdrant.collection": {
                "parameters": {
                    "baseUrl": "http://toxiproxy:16333",
                    "collection": "documents",
                }
            },
            "qdrant.point_count": {
                "parameters": {
                    "baseUrl": "http://toxiproxy:16333",
                    "collection": "documents",
                }
            },
            "qdrant.query_smoke": {
                "parameters": {
                    "baseUrl": "http://toxiproxy:16333",
                    "collection": "documents",
                    "vector": [0.1, 0.2, 0.3, 0.4],
                    "limit": 3,
                }
            },
            "rag.business_health": {
                "parameters": {
                    "url": "http://rag-api:8000/api/ask",
                    "question": "What is OpsPilot?",
                    "expectedTerms": ["OpsPilot", "fault-lab"],
                }
            },
        }

    async def _ask(self) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=self.settings.rag_url.rstrip("/"),
            transport=self.transport,
            timeout=self.settings.timeout_seconds,
            trust_env=False,
        ) as client:
            return await client.post(
                "/api/ask",
                json={"question": "What is OpsPilot?"},
            )

    async def _wait_for(self, expectation: RagExpectation) -> httpx.Response:
        last_response: httpx.Response | None = None
        for attempt in range(self.settings.recovery_attempts):
            try:
                response = await self._ask()
                last_response = response
                if self._matches(response, expectation):
                    return response
            except httpx.RequestError:
                pass
            if attempt + 1 < self.settings.recovery_attempts:
                await asyncio.sleep(self.settings.recovery_interval_seconds)
        detail = (
            f"last status={last_response.status_code}, body={last_response.text[:500]}"
            if last_response is not None
            else "no HTTP response"
        )
        raise AssertionError(f"RAG expectation was not met: {expectation}; {detail}")

    @classmethod
    def _matches(cls, response: httpx.Response, expectation: RagExpectation) -> bool:
        if response.status_code != expectation.status_code:
            return False
        return (
            expectation.retrieved_point_count is None
            or cls._point_count(response) == expectation.retrieved_point_count
        )

    @staticmethod
    def _point_count(response: httpx.Response) -> int | None:
        try:
            payload: Any = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        value = payload.get("retrievedPointCount")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _key(scenario_id: str, action: str) -> str:
        return f"lab-e2e:{scenario_id}:{action}:{uuid4()}"


async def _run_selected(scenario_ids: list[str]) -> None:
    verifier = ScenarioVerifier(E2ESettings())
    for scenario_id in scenario_ids:
        manifest = SCENARIOS.get(scenario_id)
        if manifest is None:
            raise SystemExit(f"Unknown scenario: {scenario_id}")
        result = await verifier.run(manifest)
        print(
            f"PASS {result.scenario_id}: degraded={result.degraded_status} "
            f"recovered={result.recovered_status} points={result.recovered_point_count} "
            f"incident={result.incident_id} run={result.investigation_run_id} "
            f"evidence={result.evidence_id} operation={result.observation_operation} "
            f"audit={result.audit_asserted}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpsPilot Compose Fault Lab scenarios")
    parser.add_argument("scenarios", nargs="*", choices=sorted(SCENARIOS))
    arguments = parser.parse_args()
    asyncio.run(_run_selected(arguments.scenarios or list(SCENARIOS)))


if __name__ == "__main__":
    main()
