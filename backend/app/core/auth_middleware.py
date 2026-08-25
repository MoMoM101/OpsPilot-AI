import hmac
import re
from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.context import request_id_context, trace_id_context
from app.core.principal_context import bind_principal, reset_principal
from app.domain.security import AuthenticatedPrincipal, PrincipalKind, PrincipalRole
from app.services.security import SecurityService, token_digest
from app.storage.repositories import AuditRepository

_RUNNER_SERVICE_PATHS = (
    re.compile(r"^/runner/v1/runners/register$"),
    re.compile(r"^/runner/v1/runners/[0-9a-f-]+/heartbeat$", re.IGNORECASE),
    re.compile(r"^/runner/v1/runners/[0-9a-f-]+/tasks/claim$", re.IGNORECASE),
    re.compile(
        r"^/runner/v1/runners/[0-9a-f-]+/tasks/[0-9a-f-]+/(renew|complete)$",
        re.IGNORECASE,
    ),
    re.compile(r"^/runner/v1/runners/[0-9a-f-]+/actions/claim$", re.IGNORECASE),
    re.compile(
        r"^/runner/v1/runners/[0-9a-f-]+/actions/[0-9a-f-]+/(renew|complete)$",
        re.IGNORECASE,
    ),
)
_RUNTIME_PATHS = (
    re.compile(
        r"^/internal/v1/investigation-runs/[0-9a-f-]+/checkpoints$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^/internal/v1/investigation-runs/[0-9a-f-]+/transitions$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^/internal/v1/investigation-runs/[0-9a-f-]+/hitl-waits$",
        re.IGNORECASE,
    ),
)
_INTERNAL_RESOURCE_LOCK_PATHS = (
    re.compile(r"^/internal/v1/actions/[0-9a-f-]+/lock$", re.IGNORECASE),
    re.compile(
        r"^/internal/v1/actions/[0-9a-f-]+/lock/(renew|release)$",
        re.IGNORECASE,
    ),
)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": None,
                    "request_id": request_id_context.get(),
                    "trace_id": trace_id_context.get(),
                }
            }
        ),
        headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None,
    )


class ControlPlaneAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = request.app.state.settings
        async with request.app.state.database.session_factory() as session:
            session.info["request_transaction"] = True
            request.state.db_session = session
            principal: AuthenticatedPrincipal | None = None
            context_token = None
            auth_disabled = not settings.control_plane_auth_enabled or (
                settings.environment == "test" and not settings.control_plane_bootstrap_token
            )
            if not auth_disabled and not self._is_public(request):
                authorization = request.headers.get("Authorization", "")
                scheme, _, token = authorization.partition(" ")
                security = SecurityService(session, settings)
                browser_session = None
                if scheme.lower() == "bearer" and token:
                    principal = await security.authenticate(
                        token,
                        allow_bootstrap=(
                            request.method == "POST" and request.url.path == "/api/v1/principals"
                        ),
                    )
                    request.state.auth_method = "bearer"
                else:
                    session_token = request.cookies.get(settings.browser_session_cookie_name, "")
                    authenticated = (
                        await security.authenticate_browser_session(session_token)
                        if session_token
                        else None
                    )
                    if authenticated is not None:
                        principal, browser_session = authenticated
                        request.state.auth_method = "session"
                if principal is None:
                    return _error(
                        401,
                        "INVALID_ACCESS_TOKEN"
                        if scheme.lower() == "bearer" and token
                        else "AUTHENTICATION_REQUIRED",
                        "Access token or browser Session is invalid or inactive"
                        if scheme.lower() == "bearer" and token
                        else "A valid Bearer token or browser Session is required",
                    )
                if browser_session is not None and request.method not in {
                    "GET",
                    "HEAD",
                    "OPTIONS",
                }:
                    csrf_cookie = request.cookies.get(settings.browser_csrf_cookie_name, "")
                    csrf_header = request.headers.get("X-CSRF-Token", "")
                    if (
                        not csrf_cookie
                        or not csrf_header
                        or not hmac.compare_digest(csrf_cookie, csrf_header)
                        or not hmac.compare_digest(
                            token_digest(csrf_header), browser_session.csrf_token_hash
                        )
                    ):
                        return _error(403, "CSRF_VALIDATION_FAILED", "CSRF token is invalid")
                    request.state.browser_session = browser_session
                if not self._authorized(request, principal):
                    return _error(
                        403,
                        "PERMISSION_DENIED",
                        "Principal lacks the required permission",
                    )
                request.state.principal = principal
                context_token = bind_principal(principal)
            try:
                response = await call_next(request)
                if response.status_code >= 400:
                    if session.info.get("commit_security_audit_on_error"):
                        await session.commit()
                    else:
                        await session.rollback()
                    return response
                if principal is not None and request.method not in {"GET", "HEAD", "OPTIONS"}:
                    action = {
                        ("POST", "/api/v1/auth/session/refresh"): "auth.session.refresh",
                        ("DELETE", "/api/v1/auth/session"): "auth.session.logout",
                    }.get((request.method, request.url.path), "http.write")
                    await AuditRepository(session).create(
                        occurred_at=datetime.now(UTC),
                        actor_id=principal.actor_id,
                        actor_type=principal.actor_type,
                        actor_role=principal.role.value,
                        method=request.method,
                        path=request.url.path,
                        status_code=response.status_code,
                        request_id=request_id_context.get(),
                        trace_id=trace_id_context.get(),
                        action=action,
                        outcome="success",
                        error_code=None,
                        source_ip=request.client.host if request.client else None,
                        user_agent_hash=(
                            token_digest(request.headers["User-Agent"])
                            if request.headers.get("User-Agent")
                            else None
                        ),
                    )
                await session.commit()
                return response
            except Exception:
                await session.rollback()
                raise
            finally:
                if context_token is not None:
                    reset_principal(context_token)

    @staticmethod
    def _is_public(request: Request) -> bool:
        path = request.url.path
        if request.method == "OPTIONS":
            return True
        if path in {
            "/api/v1/health",
            "/api/v1/ready",
            "/api/v1/system/mode",
            "/api/v1/setup/status",
            "/docs",
            "/openapi.json",
        }:
            return True
        if request.method == "POST" and path == "/api/v1/auth/session":
            return True
        if request.method == "POST" and path == "/api/v1/alerts/webhook/alertmanager":
            return True
        return request.method == "POST" and any(
            pattern.match(path) for pattern in _RUNNER_SERVICE_PATHS
        )

    @staticmethod
    def _authorized(request: Request, principal: AuthenticatedPrincipal) -> bool:
        path = request.url.path
        role = principal.role
        if request.method == "POST" and any(
            pattern.match(path) for pattern in _INTERNAL_RESOURCE_LOCK_PATHS
        ):
            return role == PrincipalRole.ADMIN or (
                principal.kind == PrincipalKind.SERVICE and role == PrincipalRole.RUNTIME
            )
        if request.method == "POST" and any(pattern.match(path) for pattern in _RUNTIME_PATHS):
            return principal.kind == PrincipalKind.SERVICE and role == PrincipalRole.RUNTIME
        if (
            path.startswith("/api/v1/principals")
            or path.startswith("/api/v1/outbox")
            or path.startswith("/api/v1/demo/")
            or path.startswith("/api/v1/lab/")
            or path == "/api/v1/audit-logs"
        ):
            return role == PrincipalRole.ADMIN
        if path == "/api/v1/policies" and request.method == "POST":
            return role == PrincipalRole.ADMIN
        if path == "/api/v1/system/recovery" and request.method == "POST":
            return role == PrincipalRole.ADMIN
        if path == "/api/v1/system/preflight":
            return role == PrincipalRole.ADMIN
        if path == "/api/v1/system/model-connection-check" and request.method == "POST":
            return role == PrincipalRole.ADMIN
        if path.startswith("/api/v1/policies/") and request.method in {
            "PUT",
            "PATCH",
            "DELETE",
        }:
            return role == PrincipalRole.ADMIN
        if path in {"/api/v1/auth/session/refresh", "/api/v1/auth/session"}:
            return principal.kind == PrincipalKind.USER
        if request.method == "POST" and path == "/api/v1/environments":
            return role == PrincipalRole.ADMIN
        if request.method in {"GET", "HEAD"}:
            return role in {PrincipalRole.ADMIN, PrincipalRole.OPERATOR, PrincipalRole.VIEWER}
        return role in {PrincipalRole.ADMIN, PrincipalRole.OPERATOR}
