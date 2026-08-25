import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.application import create_app
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.core.principal_context import bind_principal, reset_principal
from app.domain.actions import ActionVerificationStatus, CompensationStatus
from app.domain.incidents import IncidentStatus
from app.domain.security import AuthenticatedPrincipal, PrincipalKind, PrincipalRole
from app.services.security import SecurityService
from app.storage import (
    ActionVerificationRecord,
    Base,
    CompensationExecutionRecord,
    CompensationRequestRecord,
    EnvironmentRecord,
    IncidentRecord,
    ResourceLockRecord,
)
from app.storage.models import (
    ApiPrincipalRecord,
    ControlPlaneAuditRecord,
    ControlPlaneSetupRecord,
)
from app.storage.repositories import AuditRepository, PrincipalRepository

BOOTSTRAP_TOKEN = "test-bootstrap-control-plane-token"


@pytest.fixture
def secure_client() -> Iterator[TestClient]:
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
    with TestClient(app) as client:
        first_admin = client.post(
            "/api/v1/principals",
            headers=_auth(BOOTSTRAP_TOKEN),
            json={
                "name": "initial-admin",
                "kind": "user",
                "role": "admin",
                "unrestrictedEnvironments": True,
            },
        )
        assert first_admin.status_code == 201
        app.state.test_admin_token = first_admin.json()["accessToken"]
        yield client


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _admin_auth(client: TestClient) -> dict[str, str]:
    return _auth(str(client.app.state.test_admin_token))


def _create_principal(
    client: TestClient,
    *,
    name: str,
    role: str,
    environment_ids: list[str] | None = None,
    kind: str = "user",
    unrestricted: bool = False,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/principals",
        headers=_admin_auth(client),
        json={
            "name": name,
            "kind": kind,
            "role": role,
            "environmentIds": environment_ids or [],
            "unrestrictedEnvironments": unrestricted,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_only_admin_can_trigger_control_plane_recovery(secure_client: TestClient) -> None:
    operator = _create_principal(
        secure_client,
        name="recovery-operator",
        role="operator",
        unrestricted=True,
    )

    public_mode = secure_client.get("/api/v1/system/mode")
    operator_retry = secure_client.post(
        "/api/v1/system/recovery",
        headers=_auth(str(operator["accessToken"])),
    )
    admin_retry = secure_client.post(
        "/api/v1/system/recovery",
        headers=_admin_auth(secure_client),
    )

    assert public_mode.status_code == 200
    assert operator_retry.status_code == 403
    assert admin_retry.status_code == 200


def test_control_plane_defaults_to_authenticated_and_role_scoped(
    secure_client: TestClient,
) -> None:
    assert secure_client.get("/api/v1/health").status_code == 200
    missing = secure_client.get("/api/v1/environments")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    invalid = secure_client.get("/api/v1/environments", headers=_auth("invalid"))
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"

    first_environment = secure_client.post(
        "/api/v1/environments",
        headers=_admin_auth(secure_client),
        json={"name": "Scoped production", "slug": "scoped-production"},
    ).json()
    second_environment = secure_client.post(
        "/api/v1/environments",
        headers=_admin_auth(secure_client),
        json={"name": "Hidden staging", "slug": "hidden-staging"},
    ).json()
    first_resource = secure_client.post(
        "/api/v1/resources",
        headers=_admin_auth(secure_client),
        json={
            "environmentId": first_environment["id"],
            "name": "visible-service",
            "kind": "service",
        },
    ).json()
    second_resource = secure_client.post(
        "/api/v1/resources",
        headers=_admin_auth(secure_client),
        json={
            "environmentId": second_environment["id"],
            "name": "hidden-service",
            "kind": "service",
        },
    ).json()

    viewer = _create_principal(
        secure_client,
        name="production-viewer",
        role="viewer",
        environment_ids=[first_environment["id"]],
    )
    viewer_headers = _auth(str(viewer["accessToken"]))
    session = secure_client.get("/api/v1/auth/me", headers=viewer_headers).json()
    assert session["id"] == viewer["id"]
    assert session["role"] == "viewer"
    environments_response = secure_client.get(
        "/api/v1/environments", headers=viewer_headers
    )
    assert environments_response.headers["X-Total-Count"] == "1"
    environments = environments_response.json()
    assert [item["id"] for item in environments] == [first_environment["id"]]
    resources_response = secure_client.get("/api/v1/resources", headers=viewer_headers)
    assert resources_response.headers["X-Total-Count"] == "1"
    resources = resources_response.json()
    assert [item["id"] for item in resources] == [first_resource["id"]]
    forbidden = secure_client.post(
        "/api/v1/incidents",
        headers=viewer_headers,
        json={
            "title": "Viewer cannot mutate",
            "severity": "high",
            "resourceId": first_resource["id"],
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "PERMISSION_DENIED"

    operator = _create_principal(
        secure_client,
        name="production-operator",
        role="operator",
        environment_ids=[first_environment["id"]],
    )
    operator_headers = _auth(str(operator["accessToken"]))
    incident = secure_client.post(
        "/api/v1/incidents",
        headers=operator_headers,
        json={
            "title": "Authenticated incident",
            "severity": "high",
            "resourceId": first_resource["id"],
        },
    )
    assert incident.status_code == 201
    assert incident.json()["timeline"][0]["actorId"] == operator["id"]
    cross_scope = secure_client.post(
        "/api/v1/incidents",
        headers=operator_headers,
        json={
            "title": "Cross-scope incident",
            "severity": "high",
            "resourceId": second_resource["id"],
        },
    )
    assert cross_scope.status_code == 404
    hidden_incident = secure_client.post(
        "/api/v1/incidents",
        headers=_admin_auth(secure_client),
        json={
            "title": "Hidden timeline",
            "severity": "medium",
            "resourceId": second_resource["id"],
        },
    ).json()
    hidden_timeline = secure_client.get(
        f"/api/v1/incidents/{hidden_incident['id']}/timeline",
        headers=viewer_headers,
    )
    assert hidden_timeline.status_code == 404
    assert hidden_timeline.json()["error"]["code"] == "INCIDENT_NOT_FOUND"
    audit = secure_client.get("/api/v1/audit-logs", headers=_admin_auth(secure_client)).json()
    incident_audit = next(
        item
        for item in audit
        if item["path"] == "/api/v1/incidents" and item["actorId"] == operator["id"]
    )
    assert incident_audit["actorId"] == operator["id"]
    assert incident_audit["actorRole"] == "operator"

    deactivated = secure_client.delete(
        f"/api/v1/principals/{viewer['id']}",
        headers=_admin_auth(secure_client),
    )
    assert deactivated.status_code == 204
    rejected_viewer = secure_client.get("/api/v1/environments", headers=viewer_headers)
    assert rejected_viewer.status_code == 401


def test_action_lock_and_execution_endpoints_enforce_environment_scope(
    secure_client: TestClient,
) -> None:
    admin_headers = _admin_auth(secure_client)
    visible_environment = secure_client.post(
        "/api/v1/environments",
        headers=admin_headers,
        json={"name": "Visible action environment", "slug": "visible-action-env"},
    ).json()
    hidden_environment = secure_client.post(
        "/api/v1/environments",
        headers=admin_headers,
        json={"name": "Hidden action environment", "slug": "hidden-action-env"},
    ).json()
    hidden_resource = secure_client.post(
        "/api/v1/resources",
        headers=admin_headers,
        json={
            "environmentId": hidden_environment["id"],
            "name": "hidden-action-service",
            "kind": "service",
        },
    ).json()
    hidden_incident = secure_client.post(
        "/api/v1/incidents",
        headers=admin_headers,
        json={
            "title": "Hidden action",
            "severity": "high",
            "resourceId": hidden_resource["id"],
        },
    ).json()
    secure_client.post(
        "/api/v1/policies",
        headers=admin_headers,
        json={
            "environmentId": hidden_environment["id"],
            "name": "Hidden restart policy",
            "effect": "allow",
            "capabilities": ["container.restart"],
            "resourceIds": [hidden_resource["id"]],
        },
    )
    snapshot = secure_client.post(
        "/api/v1/policies/evaluate",
        headers=admin_headers,
        json={
            "environmentId": hidden_environment["id"],
            "incidentId": hidden_incident["id"],
            "resourceId": hidden_resource["id"],
            "capability": "container.restart",
            "autonomyLevel": "L2",
            "risk": "medium",
        },
    ).json()
    action = secure_client.post(
        "/api/v1/actions",
        headers=admin_headers,
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "parameters": {"containerId": "hidden-api"},
            "verificationCriteria": ["container becomes healthy"],
            "idempotencyKey": "hidden-environment-action-0001",
        },
    ).json()["action"]
    runner = secure_client.post(
        "/runner/v1/runners/register",
        json={
            "name": "hidden-action-runner",
            "softwareVersion": "1.0.0",
            "environmentId": hidden_environment["id"],
            "capabilities": [
                {
                    "connector": "docker",
                    "contractVersion": "1.0",
                    "observe": ["docker.container_health"],
                    "actions": ["container.restart"],
                }
            ],
        },
    ).json()
    dispatched = secure_client.post(
        f"/api/v1/actions/{action['id']}/dispatch",
        headers=admin_headers,
    )
    assert dispatched.status_code == 200
    public_lock = secure_client.get("/api/v1/resource-locks", headers=admin_headers).json()[0]
    assert "fencingToken" not in public_lock

    async def seed_compensation_execution() -> str:
        async with secure_client.app.state.database.session_factory() as session:
            lock = (
                await session.execute(
                    select(ResourceLockRecord).where(
                        ResourceLockRecord.action_request_id == UUID(action["id"])
                    )
                )
            ).scalar_one()
            verification = ActionVerificationRecord(
                action_request_id=UUID(action["id"]),
                environment_id=UUID(hidden_environment["id"]),
                incident_id=UUID(hidden_incident["id"]),
                resource_id=UUID(hidden_resource["id"]),
                status=ActionVerificationStatus.FAILED,
                criteria_snapshot=[],
                connector="docker",
                operation="docker.container_health",
                parameters={"containerId": "hidden-api"},
                compensation_required=True,
                version=1,
            )
            session.add(verification)
            await session.flush()
            compensation = CompensationRequestRecord(
                action_request_id=UUID(action["id"]),
                verification_id=verification.id,
                environment_id=UUID(hidden_environment["id"]),
                incident_id=UUID(hidden_incident["id"]),
                resource_id=UUID(hidden_resource["id"]),
                capability="container.restart",
                parameters={"containerId": "hidden-api"},
                status=CompensationStatus.APPROVED,
                idempotency_key="hidden-compensation-0001",
                request_fingerprint="0" * 64,
                requested_by="seed",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                version=1,
            )
            session.add(compensation)
            await session.flush()
            execution = CompensationExecutionRecord(
                compensation_request_id=compensation.id,
                runner_id=UUID(runner["id"]),
                status=CompensationStatus.DISPATCHING,
                execution_fencing_token=1,
                resource_fencing_token=lock.fencing_token,
                version=1,
            )
            session.add(execution)
            await session.commit()
            return str(compensation.id)

    compensation_id = asyncio.run(seed_compensation_execution())
    operator = _create_principal(
        secure_client,
        name="visible-only-operator",
        role="operator",
        environment_ids=[visible_environment["id"]],
    )
    headers = _auth(str(operator["accessToken"]))
    assert (
        secure_client.get(
            f"/api/v1/actions/{action['id']}/execution", headers=headers
        ).status_code
        == 404
    )
    for operation in ("renew", "release"):
        response = secure_client.post(
            f"/internal/v1/actions/{action['id']}/lock/{operation}",
            headers=headers,
            json={"fencingToken": 1},
        )
        assert response.status_code == 403
    assert (
        secure_client.get(
            f"/api/v1/compensations/{compensation_id}/execution", headers=headers
        ).status_code
        == 404
    )


def test_approval_requester_cannot_decide_own_request(secure_client: TestClient) -> None:
    admin_headers = _admin_auth(secure_client)
    environment = secure_client.post(
        "/api/v1/environments",
        headers=admin_headers,
        json={"name": "Separated approval", "slug": "separated-approval"},
    ).json()
    resource = secure_client.post(
        "/api/v1/resources",
        headers=admin_headers,
        json={
            "environmentId": environment["id"],
            "name": "approval-target",
            "kind": "service",
        },
    ).json()
    secure_client.post(
        "/api/v1/policies",
        headers=admin_headers,
        json={
            "environmentId": environment["id"],
            "name": "Separated restart approval",
            "effect": "allow",
            "capabilities": ["container.restart"],
            "resourceIds": [resource["id"]],
            "approvalRequired": True,
        },
    )
    requester = _create_principal(
        secure_client,
        name="approval-requester",
        role="operator",
        environment_ids=[environment["id"]],
    )
    approver = _create_principal(
        secure_client,
        name="independent-approver",
        role="operator",
        environment_ids=[environment["id"]],
    )
    requester_headers = _auth(str(requester["accessToken"]))
    incident = secure_client.post(
        "/api/v1/incidents",
        headers=requester_headers,
        json={
            "title": "Approval separation incident",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    snapshot = secure_client.post(
        "/api/v1/policies/evaluate",
        headers=requester_headers,
        json={
            "environmentId": environment["id"],
            "incidentId": incident["id"],
            "resourceId": resource["id"],
            "capability": "container.restart",
            "autonomyLevel": "L2",
            "risk": "medium",
        },
    ).json()
    approval = secure_client.post(
        "/api/v1/approvals",
        headers=requester_headers,
        json={
            "policyDecisionId": snapshot["snapshotId"],
            "parameters": {"containerId": "api"},
        },
    ).json()
    self_decision = secure_client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        headers=requester_headers,
        json={"decision": "approve", "expectedVersion": approval["version"]},
    )
    assert self_decision.status_code == 403
    assert self_decision.json()["error"]["code"] == "APPROVAL_SELF_DECISION_FORBIDDEN"
    spoofed_actor = secure_client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        headers={**requester_headers, "X-Actor-ID": str(approver["id"])},
        json={"decision": "approve", "expectedVersion": approval["version"]},
    )
    assert spoofed_actor.status_code == 403
    assert spoofed_actor.json()["error"]["code"] == "APPROVAL_SELF_DECISION_FORBIDDEN"
    independent = secure_client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        headers=_auth(str(approver["accessToken"])),
        json={"decision": "approve", "expectedVersion": approval["version"]},
    )
    assert independent.status_code == 200


def test_runtime_service_identity_isolated_from_user_mutations(
    secure_client: TestClient,
) -> None:
    operator = _create_principal(
        secure_client,
        name="operator",
        role="operator",
        unrestricted=True,
    )
    runtime = _create_principal(
        secure_client,
        name="agent-runtime",
        role="runtime",
        kind="service",
        unrestricted=True,
    )
    run_id = uuid4()
    operator_response = secure_client.post(
        f"/internal/v1/investigation-runs/{run_id}/transitions",
        headers=_auth(str(operator["accessToken"])),
        json={"target": "cancelled", "expectedVersion": 1},
    )
    assert operator_response.status_code == 403
    operator_cancel = secure_client.post(
        f"/api/v1/investigation-runs/{run_id}/cancel",
        headers=_auth(str(operator["accessToken"])),
        json={"expectedVersion": 1},
    )
    assert operator_cancel.status_code == 404
    runtime_response = secure_client.post(
        f"/internal/v1/investigation-runs/{run_id}/transitions",
        headers=_auth(str(runtime["accessToken"])),
        json={"target": "cancelled", "expectedVersion": 1},
    )
    assert runtime_response.status_code == 404
    internal_lock_path = f"/internal/v1/actions/{uuid4()}/lock"
    assert (
        secure_client.post(
            internal_lock_path,
            headers=_auth(str(operator["accessToken"])),
        ).status_code
        == 403
    )
    runtime_lock = secure_client.post(
        internal_lock_path,
        headers=_auth(str(runtime["accessToken"])),
    )
    assert runtime_lock.status_code == 404
    assert runtime_lock.json()["error"]["code"] == "ACTION_NOT_FOUND"
    runtime_read = secure_client.get(
        "/api/v1/environments",
        headers=_auth(str(runtime["accessToken"])),
    )
    assert runtime_read.status_code == 403

    bootstrap_internal = secure_client.post(
        f"/internal/v1/investigation-runs/{run_id}/transitions",
        headers=_auth(BOOTSTRAP_TOKEN),
        json={"target": "cancelled", "expectedVersion": 1},
    )
    assert bootstrap_internal.status_code == 401

    removed_user_path = secure_client.post(
        f"/api/v1/investigation-runs/{run_id}/transitions",
        headers=_auth(str(operator["accessToken"])),
        json={"target": "cancelled", "expectedVersion": 1},
    )
    assert removed_user_path.status_code == 404


def test_runtime_role_requires_service_principal(secure_client: TestClient) -> None:
    response = secure_client.post(
        "/api/v1/principals",
        headers=_admin_auth(secure_client),
        json={
            "name": "invalid-user-runtime",
            "kind": "user",
            "role": "runtime",
            "unrestrictedEnvironments": True,
        },
    )

    assert response.status_code == 422


def test_audit_failure_rolls_back_the_business_change(
    secure_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(AuditRepository, "create", fail_audit)
    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        secure_client.post(
            "/api/v1/environments",
            headers=_admin_auth(secure_client),
            json={"name": "Must Roll Back", "slug": "must-roll-back"},
        )

    async def environment_exists() -> bool:
        async with secure_client.app.state.database.session_factory() as session:
            record = await session.scalar(
                select(EnvironmentRecord).where(EnvironmentRecord.slug == "must-roll-back")
            )
            return record is not None

    assert asyncio.run(environment_exists()) is False


def test_audit_offset_pages_are_stable_for_equal_timestamps(
    secure_client: TestClient,
) -> None:
    occurred_at = datetime(2026, 8, 25, tzinfo=UTC)

    async def seed() -> list[str]:
        async with secure_client.app.state.database.session_factory() as session:
            records = [
                ControlPlaneAuditRecord(
                    occurred_at=occurred_at,
                    actor_id=f"stable-actor-{index}",
                    actor_type="user",
                    actor_role="admin",
                    method="GET",
                    path="/stable-pagination",
                    status_code=200,
                    action="stable.pagination",
                    outcome="success",
                )
                for index in range(2)
            ]
            session.add_all(records)
            await session.commit()
            return [str(record.id) for record in records]

    expected_ids = set(asyncio.run(seed()))
    pages = [
        secure_client.get(
            "/api/v1/audit-logs",
            headers=_admin_auth(secure_client),
            params={"action": "stable.pagination", "limit": 1, "offset": offset},
        )
        for offset in range(2)
    ]
    page_ids = [page.json()[0]["id"] for page in pages]
    assert len(set(page_ids)) == 2
    assert set(page_ids) == expected_ids
    assert all(page.headers["X-Total-Count"] == "2" for page in pages)


def test_browser_session_requires_csrf_rotates_and_logs_out(
    secure_client: TestClient,
) -> None:
    viewer = _create_principal(
        secure_client,
        name="browser-viewer",
        role="viewer",
        unrestricted=True,
    )
    created = secure_client.post(
        "/api/v1/auth/session",
        json={"accessToken": viewer["accessToken"]},
    )
    assert created.status_code == 201
    csrf = created.json()["csrfToken"]
    original_session_cookie = secure_client.cookies["opspilot_session"]
    assert "HttpOnly" in created.headers["set-cookie"]
    assert "SameSite=lax" in created.headers["set-cookie"]

    me = secure_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == viewer["id"]

    rejected_refresh = secure_client.post("/api/v1/auth/session/refresh")
    assert rejected_refresh.status_code == 403
    assert rejected_refresh.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"

    refreshed = secure_client.post(
        "/api/v1/auth/session/refresh",
        headers={"X-CSRF-Token": csrf},
    )
    assert refreshed.status_code == 200
    refreshed_csrf = refreshed.json()["csrfToken"]
    assert refreshed_csrf != csrf
    assert secure_client.cookies["opspilot_session"] != original_session_cookie

    logout = secure_client.delete(
        "/api/v1/auth/session",
        headers={"X-CSRF-Token": refreshed_csrf},
    )
    assert logout.status_code == 204
    assert secure_client.get("/api/v1/auth/me").status_code == 401


def test_bootstrap_token_is_invalid_after_first_admin_exists(
    secure_client: TestClient,
) -> None:
    response = secure_client.post(
        "/api/v1/principals",
        headers=_auth(BOOTSTRAP_TOKEN),
        json={
            "name": "second-bootstrap-admin",
            "kind": "user",
            "role": "admin",
            "unrestrictedEnvironments": True,
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


def test_admin_cannot_deactivate_self_or_last_unrestricted_admin(
    secure_client: TestClient,
) -> None:
    current = secure_client.get(
        "/api/v1/auth/me", headers=_admin_auth(secure_client)
    ).json()
    self_deactivation = secure_client.delete(
        f"/api/v1/principals/{current['id']}",
        headers=_admin_auth(secure_client),
    )
    assert self_deactivation.status_code == 409
    assert (
        self_deactivation.json()["error"]["code"]
        == "PRINCIPAL_SELF_DEACTIVATION_FORBIDDEN"
    )

    restricted_admin = _create_principal(
        secure_client,
        name="restricted-admin",
        role="admin",
    )
    last_admin = secure_client.delete(
        f"/api/v1/principals/{current['id']}",
        headers=_auth(str(restricted_admin["accessToken"])),
    )
    assert last_admin.status_code == 409
    assert last_admin.json()["error"]["code"] == "LAST_UNRESTRICTED_ADMIN"


def test_concurrent_admin_deactivation_preserves_one_unrestricted_admin(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "concurrent-admin-deactivation.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        database_readiness_enabled=False,
    )
    app = create_app(settings)

    async def scenario() -> tuple[list[str | None], int]:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        now = datetime.now(UTC)
        async with app.state.database.session_factory() as session:
            first = ApiPrincipalRecord(
                name="concurrent-admin-a",
                kind=PrincipalKind.USER,
                role=PrincipalRole.ADMIN,
                token_hash="a" * 64,
                token_issued_at=now,
                token_expires_at=now + timedelta(hours=1),
                environment_ids=[],
                unrestricted_environments=True,
            )
            second = ApiPrincipalRecord(
                name="concurrent-admin-b",
                kind=PrincipalKind.USER,
                role=PrincipalRole.ADMIN,
                token_hash="b" * 64,
                token_issued_at=now,
                token_expires_at=now + timedelta(hours=1),
                environment_ids=[],
                unrestricted_environments=True,
            )
            session.add_all([first, second])
            await session.flush()
            session.add(
                ControlPlaneSetupRecord(
                    key="initial_admin",
                    completed_at=now,
                    completed_by_principal_id=first.id,
                )
            )
            await session.commit()
            first_id, second_id = first.id, second.id

        async def deactivate(actor_id: UUID, target_id: UUID, name: str) -> str | None:
            principal = AuthenticatedPrincipal(
                id=actor_id,
                name=name,
                kind=PrincipalKind.USER,
                role=PrincipalRole.ADMIN,
                environment_ids=frozenset(),
                unrestricted_environments=True,
            )
            token = bind_principal(principal)
            try:
                async with app.state.database.session_factory() as session:
                    try:
                        await SecurityService(session, settings).deactivate(target_id)
                    except ApplicationError as exc:
                        await session.rollback()
                        return exc.code
                return None
            finally:
                reset_principal(token)

        results = await asyncio.gather(
            deactivate(first_id, second_id, "concurrent-admin-a"),
            deactivate(second_id, first_id, "concurrent-admin-b"),
        )
        async with app.state.database.session_factory() as session:
            remaining = await PrincipalRepository(session).count_active_unrestricted_admins(
                now=datetime.now(UTC)
            )
        await app.state.database.dispose()
        return results, remaining

    results, remaining = asyncio.run(scenario())
    assert results.count(None) == 1
    assert results.count("LAST_UNRESTRICTED_ADMIN") == 1
    assert remaining == 1


def test_principal_token_rotation_revokes_old_token_and_sessions(
    secure_client: TestClient,
) -> None:
    viewer = _create_principal(
        secure_client,
        name="rotating-viewer",
        role="viewer",
        unrestricted=True,
    )
    old_token = str(viewer["accessToken"])
    session = secure_client.post(
        "/api/v1/auth/session",
        json={"accessToken": old_token},
    )
    assert session.status_code == 201

    rotated = secure_client.post(
        f"/api/v1/principals/{viewer['id']}/rotate-token",
        headers=_admin_auth(secure_client),
    )
    assert rotated.status_code == 200
    new_token = rotated.json()["accessToken"]
    assert new_token != old_token

    assert secure_client.get("/api/v1/auth/me").status_code == 401
    assert secure_client.get("/api/v1/auth/me", headers=_auth(old_token)).status_code == 401
    assert secure_client.get("/api/v1/auth/me", headers=_auth(new_token)).status_code == 200


def test_session_authentication_events_are_audited_without_tokens(
    secure_client: TestClient,
) -> None:
    viewer = _create_principal(
        secure_client,
        name="audited-browser-viewer",
        role="viewer",
        unrestricted=True,
    )
    for _ in range(3):
        failed = secure_client.post(
            "/api/v1/auth/session",
            headers={"User-Agent": "review-security-client/1.0"},
            json={"accessToken": "invalid-token-that-is-never-persisted"},
        )
        assert failed.status_code == 401

    created = secure_client.post(
        "/api/v1/auth/session",
        headers={"User-Agent": "review-security-client/1.0"},
        json={"accessToken": viewer["accessToken"]},
    )
    csrf = created.json()["csrfToken"]
    refreshed = secure_client.post(
        "/api/v1/auth/session/refresh",
        headers={"X-CSRF-Token": csrf, "User-Agent": "review-security-client/1.0"},
    )
    refreshed_csrf = refreshed.json()["csrfToken"]
    assert (
        secure_client.delete(
            "/api/v1/auth/session",
            headers={
                "X-CSRF-Token": refreshed_csrf,
                "User-Agent": "review-security-client/1.0",
            },
        ).status_code
        == 204
    )

    audit = secure_client.get(
        "/api/v1/audit-logs",
        headers=_admin_auth(secure_client),
        params={"limit": 100},
    ).json()
    session_events = [
        item for item in audit if item["action"] and item["action"].startswith("auth.session")
    ]
    failures = [item for item in session_events if item["outcome"] == "failure"]
    assert len(failures) == 3
    assert all(item["actorId"] == "anonymous" for item in failures)
    assert all(item["errorCode"] == "INVALID_ACCESS_TOKEN" for item in failures)
    assert all(item["sourceIp"] for item in failures)
    assert all(len(item["userAgentHash"]) == 64 for item in failures)
    successes = {item["action"] for item in session_events if item["outcome"] == "success"}
    assert successes == {
        "auth.session.create",
        "auth.session.refresh",
        "auth.session.logout",
    }
    serialized = str(session_events)
    assert str(viewer["accessToken"]) not in serialized
    assert csrf not in serialized
    assert refreshed_csrf not in serialized


def test_fault_lab_control_plane_is_admin_only(secure_client: TestClient) -> None:
    operator = _create_principal(
        secure_client,
        name="lab-operator",
        role="operator",
        unrestricted=True,
    )

    forbidden = secure_client.get(
        "/api/v1/lab/scenarios",
        headers=_auth(str(operator["accessToken"])),
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "PERMISSION_DENIED"

    disabled = secure_client.get(
        "/api/v1/lab/scenarios",
        headers=_admin_auth(secure_client),
    )
    assert disabled.status_code == 404
    assert disabled.json()["error"]["code"] == "LAB_DISABLED"


def test_policy_management_is_admin_only_but_operator_can_dry_run(
    secure_client: TestClient,
) -> None:
    admin_headers = _admin_auth(secure_client)
    environment = secure_client.post(
        "/api/v1/environments",
        headers=admin_headers,
        json={"name": "Policy RBAC", "slug": "policy-rbac"},
    ).json()
    resource = secure_client.post(
        "/api/v1/resources",
        headers=_admin_auth(secure_client),
        json={
            "environmentId": environment["id"],
            "name": "policy-rbac-service",
            "kind": "service",
        },
    ).json()
    operator = _create_principal(
        secure_client,
        name="policy-operator",
        role="operator",
        environment_ids=[environment["id"]],
    )
    operator_headers = _auth(str(operator["accessToken"]))
    rule = {
        "environmentId": environment["id"],
        "name": "controlled health check",
        "effect": "allow",
        "capabilities": ["health.check"],
        "resourceIds": [resource["id"]],
    }
    forbidden = secure_client.post("/api/v1/policies", headers=operator_headers, json=rule)
    assert forbidden.status_code == 403
    created_rule = secure_client.post(
        "/api/v1/policies", headers=_admin_auth(secure_client), json=rule
    )
    assert created_rule.status_code == 201
    forbidden_update = secure_client.put(
        f"/api/v1/policies/{created_rule.json()['id']}",
        headers=operator_headers,
        json={**rule, "expectedVersion": created_rule.json()["version"]},
    )
    assert forbidden_update.status_code == 403

    decision = secure_client.post(
        "/api/v1/policies/dry-run",
        headers=operator_headers,
        json={
            "environmentId": environment["id"],
            "resourceId": resource["id"],
            "capability": "health.check",
            "autonomyLevel": "L1",
            "risk": "read_only",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["allowed"] is True
    viewer = _create_principal(
        secure_client,
        name="approval-viewer",
        role="viewer",
        environment_ids=[environment["id"]],
    )
    fake_snapshot_id = str(uuid4())
    assert (
        secure_client.post(
            "/api/v1/approvals",
            headers=_auth(str(viewer["accessToken"])),
            json={"policyDecisionId": fake_snapshot_id},
        ).status_code
        == 403
    )
    operator_attempt = secure_client.post(
        "/api/v1/approvals",
        headers=operator_headers,
        json={"policyDecisionId": fake_snapshot_id},
    )
    assert operator_attempt.status_code == 404
    assert operator_attempt.json()["error"]["code"] == "POLICY_DECISION_NOT_FOUND"
    action_body = {
        "policyDecisionId": fake_snapshot_id,
        "parameters": {},
        "verificationCriteria": ["service remains healthy"],
        "idempotencyKey": "security-action-check",
    }
    assert (
        secure_client.post(
            "/api/v1/actions",
            headers=_auth(str(viewer["accessToken"])),
            json=action_body,
        ).status_code
        == 403
    )
    operator_action = secure_client.post(
        "/api/v1/actions", headers=operator_headers, json=action_body
    )
    assert operator_action.status_code == 404
    assert operator_action.json()["error"]["code"] == "POLICY_DECISION_NOT_FOUND"
    internal_lock_path = f"/internal/v1/actions/{uuid4()}/lock"
    assert (
        secure_client.post(
            internal_lock_path,
            headers=_auth(str(viewer["accessToken"])),
        ).status_code
        == 403
    )
    assert secure_client.post(internal_lock_path, headers=operator_headers).status_code == 403
    admin_lock = secure_client.post(internal_lock_path, headers=admin_headers)
    assert admin_lock.status_code == 404
    assert admin_lock.json()["error"]["code"] == "ACTION_NOT_FOUND"


def test_dashboard_aggregates_are_environment_scoped(
    secure_client: TestClient,
) -> None:
    admin_headers = _admin_auth(secure_client)
    visible_environment = secure_client.post(
        "/api/v1/environments",
        headers=admin_headers,
        json={"name": "Dashboard visible", "slug": "dashboard-visible"},
    ).json()
    hidden_environment = secure_client.post(
        "/api/v1/environments",
        headers=admin_headers,
        json={"name": "Dashboard hidden", "slug": "dashboard-hidden"},
    ).json()

    def create_incident(environment: dict[str, object], suffix: str) -> dict[str, object]:
        resource = secure_client.post(
            "/api/v1/resources",
            headers=admin_headers,
            json={
                "environmentId": environment["id"],
                "name": f"dashboard-{suffix}",
                "kind": "service",
            },
        ).json()
        return secure_client.post(
            "/api/v1/incidents",
            headers=admin_headers,
            json={
                "title": f"Dashboard {suffix} incident",
                "severity": "high",
                "resourceId": resource["id"],
            },
        ).json()

    visible_incident = create_incident(visible_environment, "visible")
    hidden_incident = create_incident(hidden_environment, "hidden")
    for name, environment_id in (
        ("dashboard-global-runner", None),
        ("dashboard-visible-runner", visible_environment["id"]),
        ("dashboard-hidden-runner", hidden_environment["id"]),
    ):
        registered = secure_client.post(
            "/runner/v1/runners/register",
            json={
                "name": name,
                "softwareVersion": "0.1.0",
                "environmentId": environment_id,
                "capabilities": [],
            },
        )
        assert registered.status_code == 201

    async def close_hidden_incident() -> None:
        async with secure_client.app.state.database.session_factory() as session:
            record = await session.get(IncidentRecord, UUID(str(hidden_incident["id"])))
            assert record is not None
            record.status = IncidentStatus.CLOSED
            record.updated_at = datetime.now(UTC)
            await session.commit()

    asyncio.run(close_hidden_incident())
    viewer = _create_principal(
        secure_client,
        name="dashboard-scoped-viewer",
        role="viewer",
        environment_ids=[str(visible_environment["id"])],
    )
    viewer_dashboard = secure_client.get(
        "/api/v1/dashboard",
        headers=_auth(str(viewer["accessToken"])),
    )
    admin_dashboard = secure_client.get("/api/v1/dashboard", headers=admin_headers)

    assert viewer_dashboard.status_code == 200
    viewer_body = viewer_dashboard.json()
    assert viewer_body["activeTasks"] == 1
    assert viewer_body["rootCauseRate"] == 0
    assert viewer_body["meanInvestigationSeconds"] == 0
    assert viewer_body["runnerOnline"] == 2
    assert viewer_body["runnerTotal"] == 2
    assert [item["id"] for item in viewer_body["incidents"]] == [visible_incident["id"]]

    assert admin_dashboard.status_code == 200
    admin_body = admin_dashboard.json()
    assert admin_body["activeTasks"] == 1
    assert admin_body["rootCauseRate"] == 100
    assert admin_body["runnerOnline"] == 3
    assert admin_body["runnerTotal"] == 3
