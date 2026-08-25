import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from opspilot_lab.e2e import E2ESettings, ScenarioVerifier
from opspilot_lab.scenarios import SCENARIOS


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_id", sorted(SCENARIOS))
async def test_verifier_drives_each_scenario_through_admin_api_and_recovers(
    scenario_id: str,
) -> None:
    active: str | None = None
    alert_fingerprint: str | None = None
    audit_paths: list[str] = []
    incident_status = "DETECTED"
    incident_version = 1
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, alert_fingerprint, incident_status, incident_version
        calls.append((request.method, request.url.path))
        if request.url.host == "control-plane":
            if request.url.path == "/api/v1/alerts/webhook/alertmanager":
                assert request.headers["X-OpsPilot-Webhook-Token"] == "webhook-token"
                body: Any = json.loads(request.content)
                alert_fingerprint = body["alerts"][0]["fingerprint"]
                return httpx.Response(
                    202,
                    json={
                        "received": 1,
                        "created": 1,
                        "deduplicated": 0,
                        "incidentsCreated": 1,
                        "incidentsCorrelated": 0,
                        "unmatched": 0,
                    },
                )
            assert request.headers["Authorization"] == "Bearer admin-token"
            if request.method == "GET" and request.url.path == "/api/v1/environments":
                return httpx.Response(
                    200,
                    json=[{"id": "environment-1", "slug": "fault-lab"}],
                )
            if request.method == "GET" and request.url.path == "/api/v1/resources":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "resource-1",
                            "environmentId": "environment-1",
                            "name": f"rag-lab-{scenario_id}",
                        }
                    ],
                )
            if request.method == "GET" and request.url.path == "/api/v1/alerts":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "fingerprint": alert_fingerprint,
                            "incidentId": "incident-1",
                        }
                    ],
                )
            if request.method == "GET" and request.url.path == "/api/v1/audit-logs":
                return httpx.Response(
                    200,
                    json=[
                        {"method": "POST", "path": path, "outcome": "success"}
                        for path in audit_paths
                    ],
                )
            if (
                request.method == "POST"
                and request.url.path == "/api/v1/incidents/incident-1/investigation-runs"
            ):
                return httpx.Response(201, json={"id": "run-1", "status": "queued"})
            if request.method == "GET" and request.url.path == "/api/v1/incidents/incident-1":
                return httpx.Response(
                    200,
                    json={
                        "id": "incident-1",
                        "status": incident_status,
                        "version": incident_version,
                    },
                )
            if (
                request.method == "POST"
                and request.url.path == "/api/v1/incidents/incident-1/transitions"
            ):
                body = json.loads(request.content)
                assert body["expectedVersion"] == incident_version
                incident_status = body["target"]
                incident_version += 1
                return httpx.Response(
                    200,
                    json={
                        "id": "incident-1",
                        "status": incident_status,
                        "version": incident_version,
                    },
                )
            if request.method == "GET" and request.url.path == "/api/v1/investigation-runs/run-1":
                return httpx.Response(200, json={"id": "run-1", "status": "completed"})
            if request.method == "GET" and request.url.path == "/api/v1/runner-tasks":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "operation": SCENARIOS[scenario_id].expected_investigation[0],
                            "status": "succeeded",
                            "evidenceId": "evidence-1",
                        }
                    ],
                )
            if request.method == "GET" and request.url.path == "/api/v1/evidence/evidence-1":
                return httpx.Response(
                    200,
                    json={
                        "id": "evidence-1",
                        "incidentId": "incident-1",
                        "collectionStatus": "succeeded",
                    },
                )
            parts = request.url.path.split("/")
            action = parts[-1]
            requested_scenario = parts[-2]
            body = json.loads(request.content)
            assert body["idempotencyKey"].startswith(f"lab-e2e:{requested_scenario}:")
            active = requested_scenario if action == "inject" else None
            audit_paths.append(request.url.path)
            return httpx.Response(200, json={"replayed": False})

        expectation = (
            SCENARIOS[active].degraded_rag
            if active is not None
            else SCENARIOS[scenario_id].recovered_rag
        )
        body = {"retrievedPointCount": expectation.retrieved_point_count}
        return httpx.Response(expectation.status_code, json=body)

    verifier = ScenarioVerifier(
        E2ESettings(
            control_plane_url="http://control-plane/api/v1",
            access_token="admin-token",
            alertmanager_webhook_token="webhook-token",
            rag_url="http://rag-api",
            recovery_attempts=1,
            recovery_interval_seconds=0,
        ),
        transport=httpx.MockTransport(handler),
    )

    result = await verifier.run(SCENARIOS[scenario_id])

    assert result.scenario_id == scenario_id
    assert result.degraded_status == SCENARIOS[scenario_id].degraded_rag.status_code
    assert result.recovered_status == 200
    assert result.recovered_point_count == 1
    assert result.incident_id == "incident-1"
    assert result.investigation_run_id == "run-1"
    assert result.evidence_id == "evidence-1"
    assert result.observation_operation in SCENARIOS[scenario_id].expected_investigation
    assert result.audit_asserted is True
    mutation_paths = [path for method, path in calls if method == "POST" and "lab" in path]
    assert mutation_paths == [
        f"/api/v1/lab/scenarios/{scenario_id}/cleanup",
        f"/api/v1/lab/scenarios/{scenario_id}/inject",
        f"/api/v1/lab/scenarios/{scenario_id}/cleanup",
    ]


def test_verifier_requires_an_admin_access_token() -> None:
    with pytest.raises(ValueError, match="ACCESS_TOKEN"):
        ScenarioVerifier(E2ESettings(access_token="", alertmanager_webhook_token="webhook-token"))


def test_verifier_requires_the_alertmanager_webhook_token() -> None:
    with pytest.raises(ValueError, match="ALERTMANAGER_WEBHOOK_TOKEN"):
        ScenarioVerifier(E2ESettings(access_token="admin-token"))


def test_e2e_settings_load_tokens_from_compose_secret_files(tmp_path: Path) -> None:
    admin = tmp_path / "admin-token"
    webhook = tmp_path / "webhook-token"
    admin.write_text("admin-from-file", encoding="utf-8")
    webhook.write_text("webhook-from-file", encoding="utf-8")

    settings = E2ESettings(
        access_token_file=admin,
        alertmanager_webhook_token_file=webhook,
    )

    assert settings.access_token == "admin-from-file"
    assert settings.alertmanager_webhook_token == "webhook-from-file"
