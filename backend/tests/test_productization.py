import asyncio
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.application import create_app
from app.core.config import Settings
from app.storage import Base, IncidentRecord

BOOTSTRAP_TOKEN = "phase7-bootstrap-control-plane-token"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _app() -> FastAPI:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
            control_plane_auth_enabled=True,
            control_plane_bootstrap_token=BOOTSTRAP_TOKEN,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    return app


def _create_initial_admin(client: TestClient) -> str:
    response = client.post(
        "/api/v1/principals",
        headers=_auth(BOOTSTRAP_TOKEN),
        json={
            "name": "phase7-admin",
            "kind": "user",
            "role": "admin",
            "unrestrictedEnvironments": True,
        },
    )
    assert response.status_code == 201
    return str(response.json()["accessToken"])


def test_public_setup_status_tracks_one_time_initial_admin_consumption() -> None:
    app = _app()
    with TestClient(app) as client:
        pending = client.get("/api/v1/setup/status")
        admin_token = _create_initial_admin(client)
        completed = client.get("/api/v1/setup/status")
        replay = client.post(
            "/api/v1/principals",
            headers=_auth(BOOTSTRAP_TOKEN),
            json={
                "name": "replayed-bootstrap-admin",
                "kind": "user",
                "role": "admin",
                "unrestrictedEnvironments": True,
            },
        )

    assert pending.status_code == 200
    assert pending.json() == {
        "status": "initialization_required",
        "service": "OpsPilot Control Plane",
        "version": "0.1.0",
        "authenticationEnabled": True,
        "initialAdminCreated": False,
        "bootstrapAvailable": True,
    }
    assert completed.status_code == 200
    assert completed.json()["status"] == "ready"
    assert completed.json()["initialAdminCreated"] is True
    assert completed.json()["bootstrapAvailable"] is False
    assert "token" not in str(completed.json()).lower()
    assert admin_token
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


def test_deployment_preflight_is_admin_only_and_separates_blockers_from_warnings() -> None:
    app = _app()
    with TestClient(app) as client:
        admin_token = _create_initial_admin(client)
        admin_headers = _auth(admin_token)
        operator = client.post(
            "/api/v1/principals",
            headers=admin_headers,
            json={
                "name": "phase7-operator",
                "kind": "user",
                "role": "operator",
                "unrestrictedEnvironments": True,
            },
        ).json()
        forbidden = client.get(
            "/api/v1/system/preflight",
            headers=_auth(str(operator["accessToken"])),
        )
        before = client.get("/api/v1/system/preflight", headers=admin_headers)
        environment = client.post(
            "/api/v1/environments",
            headers=admin_headers,
            json={"name": "Demo", "slug": "demo"},
        )
        after = client.get("/api/v1/system/preflight", headers=admin_headers)

    assert forbidden.status_code == 403
    assert before.status_code == 200
    assert before.json()["status"] == "action_required"
    before_checks = {item["key"]: item for item in before.json()["checks"]}
    assert before_checks["environment"]["status"] == "action_required"
    assert before_checks["runner"]["status"] == "warning"
    assert before_checks["agent_runtime"]["status"] == "warning"
    assert environment.status_code == 201
    assert after.status_code == 200
    assert after.json()["status"] == "ready"
    after_checks = {item["key"]: item for item in after.json()["checks"]}
    assert after_checks["environment"]["status"] == "pass"
    serialized = str(after.json())
    assert BOOTSTRAP_TOKEN not in serialized
    assert "phase7-admin" not in serialized


def test_model_connection_check_is_admin_only_and_has_no_request_contract() -> None:
    app = _app()
    with TestClient(app) as client:
        admin_token = _create_initial_admin(client)
        admin_headers = _auth(admin_token)
        operator = client.post(
            "/api/v1/principals",
            headers=admin_headers,
            json={
                "name": "model-check-operator",
                "kind": "user",
                "role": "operator",
                "unrestrictedEnvironments": True,
            },
        ).json()
        forbidden = client.post(
            "/api/v1/system/model-connection-check",
            headers=_auth(str(operator["accessToken"])),
        )
        disabled = client.post(
            "/api/v1/system/model-connection-check",
            headers=admin_headers,
        )

    assert forbidden.status_code == 403
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["connectivityChecked"] is False
    operation = app.openapi()["paths"]["/api/v1/system/model-connection-check"]["post"]
    assert "requestBody" not in operation


def test_console_lists_expose_compatible_pagination_headers_and_filtered_totals() -> None:
    app = _app()
    with TestClient(app) as client:
        admin_token = _create_initial_admin(client)
        headers = _auth(admin_token)
        environment = client.post(
            "/api/v1/environments",
            headers=headers,
            json={"name": "Pagination", "slug": "pagination"},
        ).json()
        resource = client.post(
            "/api/v1/resources",
            headers=headers,
            json={
                "environmentId": environment["id"],
                "name": "api-1",
                "kind": "service",
                "attributes": {"externalRef": "service/api-1"},
            },
        ).json()
        for title, severity in (("Critical incident", "critical"), ("High incident", "high")):
            created = client.post(
                "/api/v1/incidents",
                headers=headers,
                json={"title": title, "severity": severity, "resourceId": resource["id"]},
            )
            assert created.status_code == 201

        first_page = client.get("/api/v1/incidents?limit=1&offset=0", headers=headers)
        filtered = client.get("/api/v1/incidents?severity=critical", headers=headers)
        empty_lists = [
            client.get(path, headers=headers)
            for path in (
                "/api/v1/alerts",
                "/api/v1/approvals",
                "/api/v1/actions",
                "/api/v1/action-proposals",
                "/api/v1/compensations",
                "/api/v1/outbox/dead-letters",
                f"/api/v1/policies?environmentId={environment['id']}",
            )
        ]
        principals = client.get("/api/v1/principals?limit=1&offset=0", headers=headers)
        audit = client.get("/api/v1/audit-logs?outcome=success&limit=2", headers=headers)

    assert len(first_page.json()) == 1
    assert first_page.headers["X-Total-Count"] == "2"
    assert first_page.headers["X-Limit"] == "1"
    assert first_page.headers["X-Offset"] == "0"
    assert filtered.headers["X-Total-Count"] == "1"
    assert all(response.status_code == 200 for response in empty_lists)
    assert all(response.headers["X-Total-Count"] == "0" for response in empty_lists)
    assert principals.status_code == 200
    assert principals.headers["X-Total-Count"] == "1"
    assert principals.headers["X-Limit"] == "1"
    assert principals.headers["X-Offset"] == "0"
    assert audit.status_code == 200
    assert int(audit.headers["X-Total-Count"]) >= len(audit.json())
    assert all(item["outcome"] == "success" for item in audit.json())

    openapi = app.openapi()
    for path in (
        "/api/v1/incidents",
        "/api/v1/alerts",
        "/api/v1/approvals",
        "/api/v1/actions",
        "/api/v1/action-proposals",
        "/api/v1/compensations",
        "/api/v1/outbox/dead-letters",
        "/api/v1/policies",
        "/api/v1/principals",
        "/api/v1/audit-logs",
    ):
        response_headers = openapi["paths"][path]["get"]["responses"]["200"]["headers"]
        assert set(response_headers) == {"X-Total-Count", "X-Limit", "X-Offset"}


def test_incident_list_filters_and_equal_timestamp_pagination_are_deterministic() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _auth(_create_initial_admin(client))
        production = client.post(
            "/api/v1/environments",
            headers=headers,
            json={"name": "Production Search", "slug": "production-search"},
        ).json()
        staging = client.post(
            "/api/v1/environments",
            headers=headers,
            json={"name": "Staging Search", "slug": "staging-search"},
        ).json()
        resources = [
            client.post(
                "/api/v1/resources",
                headers=headers,
                json={
                    "environmentId": environment_id,
                    "name": resource_name,
                    "kind": "service",
                },
            ).json()
            for environment_id, resource_name in (
                (production["id"], "checkout-search-api"),
                (production["id"], "payment-search-api"),
                (staging["id"], "catalog-search-api"),
            )
        ]
        incidents = [
            client.post(
                "/api/v1/incidents",
                headers=headers,
                json={
                    "title": title,
                    "severity": severity,
                    "resourceId": resource["id"],
                    "owner": owner,
                },
            ).json()
            for title, severity, resource, owner in (
                ("Checkout latency search marker", "high", resources[0], "alice-search"),
                ("Payment timeout search marker", "critical", resources[1], "bob-search"),
                ("Catalog staging search marker", "medium", resources[2], "carol-search"),
            )
        ]

        async def align_timestamps() -> None:
            async with app.state.database.session_factory() as session:
                await session.execute(
                    update(IncidentRecord)
                    .where(IncidentRecord.id.in_([UUID(item["id"]) for item in incidents]))
                    .values(updated_at=datetime(2026, 8, 25, tzinfo=UTC))
                )
                await session.commit()

        asyncio.run(align_timestamps())
        pages = [
            client.get(
                "/api/v1/incidents",
                headers=headers,
                params={"limit": 1, "offset": offset},
            )
            for offset in range(3)
        ]
        production_page = client.get(
            "/api/v1/incidents",
            headers=headers,
            params={"environmentId": production["id"]},
        )
        query_cases = {
            incidents[0]["id"][:12]: incidents[0]["id"],
            "Payment timeout": incidents[1]["id"],
            "catalog-search-api": incidents[2]["id"],
            "alice-search": incidents[0]["id"],
        }
        query_responses = {
            query: client.get(
                "/api/v1/incidents", headers=headers, params={"q": query}
            )
            for query in query_cases
        }

    page_ids = [response.json()[0]["id"] for response in pages]
    assert len(set(page_ids)) == 3
    assert set(page_ids) == {item["id"] for item in incidents}
    assert all(response.headers["X-Total-Count"] == "3" for response in pages)
    assert production_page.headers["X-Total-Count"] == "2"
    assert {item["id"] for item in production_page.json()} == {
        incidents[0]["id"],
        incidents[1]["id"],
    }
    for query, expected_id in query_cases.items():
        response = query_responses[query]
        assert response.headers["X-Total-Count"] == "1"
        assert [item["id"] for item in response.json()] == [expected_id]
    parameter_names = {
        parameter["name"]
        for parameter in app.openapi()["paths"]["/api/v1/incidents"]["get"]["parameters"]
    }
    assert {"environmentId", "q"}.issubset(parameter_names)


def test_validation_errors_never_echo_sensitive_request_input() -> None:
    app = _app()
    secret = "short-secret-token"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/session",
            json={"accessToken": secret},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert secret not in response.text
    assert body["error"]["details"] == [
        {
            "type": "string_too_short",
            "location": ["body", "accessToken"],
            "message": "String should have at least 20 characters",
        }
    ]
    validation_response = app.openapi()["paths"]["/api/v1/auth/session"]["post"]["responses"][
        "422"
    ]
    assert validation_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ValidationErrorResponse"
    }
