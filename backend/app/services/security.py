import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.core.principal_context import principal_context
from app.domain.security import AuthenticatedPrincipal, PrincipalKind, PrincipalRole
from app.storage.models import ApiPrincipalRecord, BrowserSessionRecord
from app.storage.repositories import (
    BrowserSessionRepository,
    EnvironmentRepository,
    PrincipalRepository,
)
from app.storage.transactions import commit_session


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BrowserSessionCredentials:
    session: BrowserSessionRecord
    session_token: str
    csrf_token: str


class SecurityService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.principals = PrincipalRepository(session)
        self.browser_sessions = BrowserSessionRepository(session)

    async def authenticate(
        self,
        token: str,
        *,
        allow_bootstrap: bool = False,
    ) -> AuthenticatedPrincipal | None:
        bootstrap = self.settings.control_plane_bootstrap_token
        if bootstrap and hmac.compare_digest(token, bootstrap):
            setup = await self.principals.get_initial_admin_setup()
            initialized = (
                setup.completed_at is not None
                if setup is not None
                else await self.principals.has_active_admin()
            )
            if not allow_bootstrap or initialized:
                return None
            return AuthenticatedPrincipal(
                id=None,
                name="bootstrap-admin",
                kind=PrincipalKind.USER,
                role=PrincipalRole.ADMIN,
                environment_ids=frozenset(),
                unrestricted_environments=True,
            )
        record = await self.principals.get_by_token_hash(token_digest(token))
        if record is None or self._as_utc(record.token_expires_at) <= datetime.now(UTC):
            return None
        return self.to_principal(record)

    async def create_principal(
        self,
        *,
        name: str,
        kind: PrincipalKind,
        role: PrincipalRole,
        environment_ids: list[UUID],
        unrestricted_environments: bool,
    ) -> tuple[ApiPrincipalRecord, str]:
        actor = principal_context.get()
        setup = None
        if actor is not None and actor.id is None:
            if (
                kind != PrincipalKind.USER
                or role != PrincipalRole.ADMIN
                or not unrestricted_environments
            ):
                raise ApplicationError(
                    "BOOTSTRAP_ADMIN_REQUIRED",
                    "Bootstrap token may only create the first unrestricted user Admin",
                    403,
                )
            setup = await self.principals.get_initial_admin_setup(for_update=True)
            if setup is None:
                if await self.principals.has_active_admin():
                    raise ApplicationError(
                        "BOOTSTRAP_ALREADY_CONSUMED",
                        "Initial Admin setup has already completed",
                        409,
                    )
                setup = await self.principals.create_initial_admin_setup()
            if setup.completed_at is not None:
                raise ApplicationError(
                    "BOOTSTRAP_ALREADY_CONSUMED",
                    "Initial Admin setup has already completed",
                    409,
                )
        if role == PrincipalRole.RUNTIME and kind != PrincipalKind.SERVICE:
            raise ApplicationError(
                "INVALID_RUNTIME_PRINCIPAL",
                "Runtime principals must use the service kind",
                422,
            )
        environments = EnvironmentRepository(self.session)
        for environment_id in environment_ids:
            if await environments.get(environment_id) is None:
                raise ApplicationError(
                    "ENVIRONMENT_SCOPE_NOT_FOUND",
                    "Every principal Environment scope must exist and be assignable",
                    422,
                )
        raw_token = secrets.token_urlsafe(32)
        issued_at = datetime.now(UTC)
        try:
            record = await self.principals.create(
                name=name,
                kind=kind,
                role=role,
                token_hash=token_digest(raw_token),
                token_issued_at=issued_at,
                token_expires_at=issued_at
                + timedelta(seconds=self.settings.principal_token_ttl_seconds),
                environment_ids=[str(item) for item in environment_ids],
                unrestricted_environments=unrestricted_environments,
            )
        except IntegrityError as exc:
            raise ApplicationError(
                "PRINCIPAL_NAME_CONFLICT", "Principal name already exists", 409
            ) from exc
        if setup is not None:
            setup.completed_at = issued_at
            setup.completed_by_principal_id = record.id
            await self.session.flush()
        await commit_session(self.session)
        return record, raw_token

    async def rotate_principal_token(
        self,
        principal_id: UUID,
    ) -> tuple[ApiPrincipalRecord, str]:
        record = await self.principals.get(principal_id, for_update=True)
        if record is None or not record.active:
            raise ApplicationError("PRINCIPAL_NOT_FOUND", "Principal does not exist", 404)
        raw_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        record.token_hash = token_digest(raw_token)
        record.token_issued_at = now
        record.token_expires_at = now + timedelta(seconds=self.settings.principal_token_ttl_seconds)
        record.updated_at = now
        await self.browser_sessions.revoke_for_principal(record.id, now)
        await commit_session(self.session)
        return record, raw_token

    async def deactivate(self, principal_id: UUID) -> None:
        actor = principal_context.get()
        if actor is not None and actor.id == principal_id:
            raise ApplicationError(
                "PRINCIPAL_SELF_DEACTIVATION_FORBIDDEN",
                "The current Admin cannot deactivate its own Principal",
                409,
            )
        if not await self.principals.lock_admin_deactivation():
            raise ApplicationError(
                "CONTROL_PLANE_SETUP_MISSING",
                "Control Plane setup state is unavailable",
                503,
            )
        record = await self.principals.get(principal_id, for_update=True)
        if record is None:
            raise ApplicationError("PRINCIPAL_NOT_FOUND", "Principal does not exist", 404)
        now = datetime.now(UTC)
        is_unrestricted_admin = (
            record.active
            and record.kind == PrincipalKind.USER
            and record.role == PrincipalRole.ADMIN
            and record.unrestricted_environments
            and self._as_utc(record.token_expires_at) > now
        )
        if is_unrestricted_admin and not await self.principals.count_active_unrestricted_admins(
            exclude_id=record.id,
            now=now,
        ):
            raise ApplicationError(
                "LAST_UNRESTRICTED_ADMIN",
                "At least one active unrestricted user Admin must remain",
                409,
            )
        record.active = False
        record.updated_at = now
        await self.browser_sessions.revoke_for_principal(record.id, now)
        await commit_session(self.session)

    async def create_browser_session(
        self,
        access_token: str,
        user_agent: str | None,
    ) -> tuple[AuthenticatedPrincipal, BrowserSessionCredentials]:
        principal = await self.authenticate(access_token)
        if principal is None or principal.id is None or principal.kind != PrincipalKind.USER:
            raise ApplicationError(
                "INVALID_ACCESS_TOKEN",
                "A valid user Principal token is required",
                401,
            )
        credentials = await self._new_browser_session(principal.id, user_agent)
        await commit_session(self.session)
        return principal, credentials

    async def authenticate_browser_session(
        self,
        session_token: str,
    ) -> tuple[AuthenticatedPrincipal, BrowserSessionRecord] | None:
        record = await self.browser_sessions.get_by_token_hash(token_digest(session_token))
        now = datetime.now(UTC)
        if (
            record is None
            or record.revoked_at is not None
            or self._as_utc(record.expires_at) <= now
            or self._as_utc(record.absolute_expires_at) <= now
        ):
            return None
        principal_record = await self.principals.get(record.principal_id)
        if principal_record is None or not principal_record.active:
            return None
        record.last_used_at = now
        return self.to_principal(principal_record), record

    async def refresh_browser_session(
        self,
        session_token: str,
        user_agent: str | None,
    ) -> BrowserSessionCredentials:
        existing = await self.browser_sessions.get_by_token_hash(
            token_digest(session_token), for_update=True
        )
        now = datetime.now(UTC)
        if (
            existing is None
            or existing.revoked_at is not None
            or self._as_utc(existing.expires_at) <= now
            or self._as_utc(existing.absolute_expires_at) <= now
        ):
            raise ApplicationError("SESSION_EXPIRED", "Browser Session has expired", 401)
        existing.revoked_at = now
        credentials = await self._new_browser_session(
            existing.principal_id,
            user_agent,
            absolute_expires_at=self._as_utc(existing.absolute_expires_at),
        )
        await commit_session(self.session)
        return credentials

    async def revoke_browser_session(self, session_token: str) -> None:
        record = await self.browser_sessions.get_by_token_hash(
            token_digest(session_token), for_update=True
        )
        if record is not None and record.revoked_at is None:
            record.revoked_at = datetime.now(UTC)
        await commit_session(self.session)

    async def _new_browser_session(
        self,
        principal_id: UUID,
        user_agent: str | None,
        *,
        absolute_expires_at: datetime | None = None,
    ) -> BrowserSessionCredentials:
        now = datetime.now(UTC)
        absolute_expiry = absolute_expires_at or now + timedelta(
            seconds=self.settings.browser_session_absolute_ttl_seconds
        )
        expiry = min(
            now + timedelta(seconds=self.settings.browser_session_ttl_seconds),
            absolute_expiry,
        )
        session_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        record = await self.browser_sessions.create(
            principal_id=principal_id,
            token_hash=token_digest(session_token),
            csrf_token_hash=token_digest(csrf_token),
            expires_at=expiry,
            absolute_expires_at=absolute_expiry,
            last_used_at=now,
            user_agent_hash=token_digest(user_agent) if user_agent else None,
        )
        return BrowserSessionCredentials(record, session_token, csrf_token)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @staticmethod
    def to_principal(record: ApiPrincipalRecord) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            id=record.id,
            name=record.name,
            kind=record.kind,
            role=record.role,
            environment_ids=frozenset(UUID(item) for item in record.environment_ids),
            unrestricted_environments=record.unrestricted_environments,
        )
