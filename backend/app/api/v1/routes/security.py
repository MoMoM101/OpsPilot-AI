from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.core.context import request_id_context, trace_id_context
from app.core.errors import ApplicationError
from app.core.logging import get_logger
from app.domain.security import AuthenticatedPrincipal
from app.schemas.security import (
    AuditRecordResponse,
    BrowserSessionCreate,
    BrowserSessionResponse,
    PrincipalCreate,
    PrincipalCreateResponse,
    PrincipalResponse,
    PrincipalSessionResponse,
    PrincipalTokenRotateResponse,
)
from app.services.security import SecurityService, token_digest
from app.storage.repositories import AuditRepository, PrincipalRepository

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
logger = get_logger(__name__)


def _source(request: Request) -> tuple[str | None, str | None]:
    user_agent = request.headers.get("User-Agent")
    return (
        request.client.host if request.client else None,
        token_digest(user_agent) if user_agent else None,
    )


async def _record_session_audit(
    session: AsyncSession,
    request: Request,
    *,
    actor: AuthenticatedPrincipal | None,
    outcome: str,
    status_code: int,
    error_code: str | None = None,
) -> None:
    source_ip, user_agent_hash = _source(request)
    await AuditRepository(session).create(
        occurred_at=datetime.now(UTC),
        actor_id=actor.actor_id if actor else "anonymous",
        actor_type=actor.actor_type if actor else "anonymous",
        actor_role=actor.role.value if actor else "unauthenticated",
        method=request.method,
        path=request.url.path,
        status_code=status_code,
        request_id=request_id_context.get(),
        trace_id=trace_id_context.get(),
        action="auth.session.create",
        outcome=outcome,
        error_code=error_code,
        source_ip=source_ip,
        user_agent_hash=user_agent_hash,
    )


def _principal_session(principal: AuthenticatedPrincipal) -> PrincipalSessionResponse:
    return PrincipalSessionResponse(
        id=principal.id,
        name=principal.name,
        kind=principal.kind,
        role=principal.role,
        environment_ids=list(principal.environment_ids),
        unrestricted_environments=principal.unrestricted_environments,
    )


def _set_session_cookies(
    response: Response,
    request: Request,
    session_token: str,
    csrf_token: str,
    max_age: int,
) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        settings.browser_session_cookie_name,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.browser_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.browser_csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.browser_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.get("/auth/me", response_model=PrincipalSessionResponse)
async def get_current_principal(request: Request) -> PrincipalSessionResponse:
    return _principal_session(request.state.principal)


@router.post(
    "/auth/session",
    response_model=BrowserSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_browser_session(
    body: BrowserSessionCreate,
    request: Request,
    response: Response,
    session: Session,
) -> BrowserSessionResponse:
    settings = request.app.state.settings
    try:
        principal, credentials = await SecurityService(session, settings).create_browser_session(
            body.access_token,
            request.headers.get("User-Agent"),
        )
    except ApplicationError as exc:
        await _record_session_audit(
            session,
            request,
            actor=None,
            outcome="failure",
            status_code=exc.status_code,
            error_code=exc.code,
        )
        session.info["commit_security_audit_on_error"] = True
        failure_count = await AuditRepository(session).recent_auth_failure_count(
            source_ip=request.client.host if request.client else None,
            since=datetime.now(UTC) - timedelta(minutes=15),
        )
        logger.warning(
            "browser_session_authentication_failed",
            source_ip=request.client.host if request.client else None,
            error_code=exc.code,
            failures_in_15_minutes=failure_count,
        )
        raise
    await _record_session_audit(
        session,
        request,
        actor=principal,
        outcome="success",
        status_code=status.HTTP_201_CREATED,
    )
    _set_session_cookies(
        response,
        request,
        credentials.session_token,
        credentials.csrf_token,
        settings.browser_session_ttl_seconds,
    )
    return BrowserSessionResponse(
        principal=_principal_session(principal),
        csrf_token=credentials.csrf_token,
        expires_at=credentials.session.expires_at,
        absolute_expires_at=credentials.session.absolute_expires_at,
    )


@router.post("/auth/session/refresh", response_model=BrowserSessionResponse)
async def refresh_browser_session(
    request: Request,
    response: Response,
    session: Session,
) -> BrowserSessionResponse:
    settings = request.app.state.settings
    session_token = request.cookies[settings.browser_session_cookie_name]
    credentials = await SecurityService(session, settings).refresh_browser_session(
        session_token,
        request.headers.get("User-Agent"),
    )
    _set_session_cookies(
        response,
        request,
        credentials.session_token,
        credentials.csrf_token,
        settings.browser_session_ttl_seconds,
    )
    return BrowserSessionResponse(
        principal=_principal_session(request.state.principal),
        csrf_token=credentials.csrf_token,
        expires_at=credentials.session.expires_at,
        absolute_expires_at=credentials.session.absolute_expires_at,
    )


@router.delete("/auth/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout_browser_session(request: Request, session: Session) -> Response:
    settings = request.app.state.settings
    token = request.cookies.get(settings.browser_session_cookie_name, "")
    if token:
        await SecurityService(session, settings).revoke_browser_session(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.browser_session_cookie_name, path="/")
    response.delete_cookie(settings.browser_csrf_cookie_name, path="/")
    return response


@router.post(
    "/principals",
    response_model=PrincipalCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_principal(
    body: PrincipalCreate,
    request: Request,
    session: Session,
) -> PrincipalCreateResponse:
    record, token = await SecurityService(
        session,
        request.app.state.settings,
    ).create_principal(
        name=body.name,
        kind=body.kind,
        role=body.role,
        environment_ids=body.environment_ids,
        unrestricted_environments=body.unrestricted_environments,
    )
    principal = PrincipalResponse.model_validate(record)
    return PrincipalCreateResponse(**principal.model_dump(), access_token=token)


@router.get("/principals", response_model=list[PrincipalResponse], responses=PAGINATION_RESPONSE)
async def list_principals(
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PrincipalResponse]:
    repository = PrincipalRepository(session)
    records = await repository.list(limit=limit, offset=offset)
    total = await repository.count()
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [PrincipalResponse.model_validate(record) for record in records]


@router.delete("/principals/{principal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_principal(
    principal_id: UUID,
    request: Request,
    session: Session,
) -> Response:
    await SecurityService(session, request.app.state.settings).deactivate(principal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/principals/{principal_id}/rotate-token",
    response_model=PrincipalTokenRotateResponse,
)
async def rotate_principal_token(
    principal_id: UUID,
    request: Request,
    session: Session,
) -> PrincipalTokenRotateResponse:
    record, token = await SecurityService(
        session, request.app.state.settings
    ).rotate_principal_token(principal_id)
    return PrincipalTokenRotateResponse(
        principal_id=record.id,
        access_token=token,
        token_issued_at=record.token_issued_at,
        token_expires_at=record.token_expires_at,
    )


@router.get("/audit-logs", response_model=list[AuditRecordResponse], responses=PAGINATION_RESPONSE)
async def list_audit_logs(
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    actor_id: Annotated[str | None, Query(alias="actorId", min_length=1, max_length=100)] = None,
    action: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    outcome: Annotated[str | None, Query(min_length=1, max_length=30)] = None,
    occurred_from: Annotated[datetime | None, Query(alias="from")] = None,
    occurred_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> list[AuditRecordResponse]:
    if occurred_from is not None and occurred_to is not None and occurred_from > occurred_to:
        raise ApplicationError("INVALID_TIME_RANGE", "from must not be later than to")
    repository = AuditRepository(session)
    records = await repository.list(
        limit,
        offset,
        actor_id=actor_id,
        action=action,
        outcome=outcome,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    total = await repository.count(
        actor_id=actor_id,
        action=action,
        outcome=outcome,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [AuditRecordResponse.model_validate(record) for record in records]
