import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.runners import RunnerStatus
from app.services.observability import ObservabilityService
from app.storage.models import RunnerLeaseRecord, RunnerRecord
from app.storage.repositories import (
    EnvironmentRepository,
    RunnerLeaseRepository,
    RunnerRepository,
)
from app.storage.transactions import commit_session

_SENSITIVE_LABEL_PARTS = ("authorization", "cookie", "password", "secret", "token")


@dataclass(frozen=True, slots=True)
class RunnerRegistration:
    runner: RunnerRecord
    access_token: str
    fencing_token: int


@dataclass(frozen=True, slots=True)
class HeartbeatResult:
    runner: RunnerRecord
    fencing_token: int
    duplicate: bool
    access_token: str | None


class RunnerService:
    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def __init__(
        self,
        session: AsyncSession,
        lease_seconds: int,
        *,
        token_rotation_seconds: int = 86400,
        token_ttl_seconds: int = 604800,
        token_grace_seconds: int = 600,
    ) -> None:
        self.session = session
        self.lease_duration = timedelta(seconds=lease_seconds)
        self.token_rotation_duration = timedelta(seconds=token_rotation_seconds)
        self.token_ttl_duration = timedelta(seconds=token_ttl_seconds)
        self.token_grace_duration = timedelta(seconds=token_grace_seconds)
        self.runners = RunnerRepository(session)
        self.leases = RunnerLeaseRepository(session)
        self.environments = EnvironmentRepository(session)

    async def register(
        self,
        *,
        name: str,
        software_version: str,
        environment_id: UUID | None,
        capabilities: list[dict[str, Any]],
        labels: dict[str, str],
    ) -> RunnerRegistration:
        if await self.runners.get_by_name(name):
            raise ApplicationError("RUNNER_NAME_CONFLICT", "Runner name already exists", 409)
        if environment_id and await self.environments.get(environment_id) is None:
            raise ApplicationError("ENVIRONMENT_NOT_FOUND", "Environment does not exist", 404)
        access_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires_at = now + self.lease_duration
        runner = await self.runners.create(
            name=name,
            software_version=software_version,
            environment_id=environment_id,
            capabilities=capabilities,
            labels=self._redact_labels(labels),
            token_hash=self._hash_token(access_token),
            token_issued_at=now,
            token_expires_at=now + self.token_ttl_duration,
            now=now,
            lease_expires_at=expires_at,
        )
        lease = await self.leases.create(runner.id, now, expires_at)
        await commit_session(self.session)
        return RunnerRegistration(runner, access_token, lease.fencing_token)

    async def heartbeat(
        self,
        *,
        runner_id: UUID,
        access_token: str,
        heartbeat_id: UUID,
        software_version: str | None,
        capabilities: list[dict[str, Any]] | None,
        labels: dict[str, str] | None,
    ) -> HeartbeatResult:
        runner = await self.runners.get(runner_id, for_update=True)
        if runner is None:
            raise ApplicationError("RUNNER_NOT_FOUND", "Runner does not exist", 404)
        now = datetime.now(UTC)
        token_kind = self._verify_access_token(runner, access_token, now)
        if runner.status == RunnerStatus.DISABLED:
            raise ApplicationError("RUNNER_DISABLED", "Runner is disabled", 403)
        lease = await self.leases.get_for_runner(runner_id, for_update=True)
        if lease is None:
            raise ApplicationError("RUNNER_LEASE_NOT_FOUND", "Runner lease does not exist", 409)
        rotated_token = self._rotate_token_if_needed(
            runner,
            access_token,
            now,
            recovering=token_kind == "previous",
        )
        if runner.last_heartbeat_id == heartbeat_id:
            if rotated_token is not None:
                runner.version += 1
                runner.updated_at = now
                await commit_session(self.session)
            return HeartbeatResult(runner, lease.fencing_token, True, rotated_token)

        expires_at = now + self.lease_duration
        was_offline = runner.status == RunnerStatus.OFFLINE
        if was_offline:
            runner.status = RunnerStatus.ONLINE
        runner.last_seen_at = now
        runner.lease_expires_at = expires_at
        runner.last_heartbeat_id = heartbeat_id
        runner.version += 1
        runner.updated_at = now
        if software_version is not None:
            runner.software_version = software_version
        if capabilities is not None:
            runner.capabilities = {"connectors": capabilities}
        if labels is not None:
            runner.labels = self._redact_labels(labels)
        lease.renewed_at = now
        lease.expires_at = expires_at
        lease.fencing_token += 1
        if was_offline:
            await ObservabilityService(self.session).restore_for_runner(runner.id, now)
        await commit_session(self.session)
        return HeartbeatResult(runner, lease.fencing_token, False, rotated_token)

    async def authorize(
        self,
        runner_id: UUID,
        access_token: str,
    ) -> tuple[RunnerRecord, RunnerLeaseRecord]:
        runner = await self.runners.get(runner_id, for_update=True)
        if runner is None:
            raise ApplicationError("RUNNER_NOT_FOUND", "Runner does not exist", 404)
        self._verify_access_token(runner, access_token, datetime.now(UTC))
        if runner.status != RunnerStatus.ONLINE:
            raise ApplicationError("RUNNER_NOT_ONLINE", "Runner is not online", 409)
        lease = await self.leases.get_for_runner(runner_id, for_update=True)
        if lease is None:
            raise ApplicationError("RUNNER_LEASE_NOT_FOUND", "Runner lease does not exist", 409)
        if self._as_utc(lease.expires_at) <= datetime.now(UTC):
            await ObservabilityService(self.session).expire_stale_runners()
            raise ApplicationError("RUNNER_LEASE_EXPIRED", "Runner lease has expired", 409)
        return runner, lease

    async def list_runners(
        self,
        limit: int,
        offset: int,
        status: RunnerStatus | None,
    ) -> tuple[list[RunnerRecord], int]:
        await ObservabilityService(self.session).expire_stale_runners()
        records = await self.runners.list(limit, offset, status)
        total = await self.runners.count(status)
        return records, total

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _verify_access_token(
        self,
        runner: RunnerRecord,
        provided: str,
        now: datetime,
    ) -> str:
        provided_hash = self._hash_token(provided)
        if secrets.compare_digest(runner.token_hash, provided_hash):
            if self._as_utc(runner.token_expires_at) <= now:
                raise ApplicationError("RUNNER_TOKEN_EXPIRED", "Runner token has expired", 401)
            return "current"
        if runner.previous_token_hash and secrets.compare_digest(
            runner.previous_token_hash,
            provided_hash,
        ):
            if (
                runner.previous_token_expires_at is not None
                and self._as_utc(runner.previous_token_expires_at) > now
            ):
                return "previous"
            raise ApplicationError("RUNNER_TOKEN_EXPIRED", "Runner token has expired", 401)
        raise ApplicationError(
            "INVALID_RUNNER_TOKEN",
            "Runner authentication failed",
            401,
        )

    def _rotate_token_if_needed(
        self,
        runner: RunnerRecord,
        provided: str,
        now: datetime,
        *,
        recovering: bool,
    ) -> str | None:
        rotation_due = self._as_utc(runner.token_issued_at) + self.token_rotation_duration
        if not recovering and now < rotation_due:
            return None
        access_token = secrets.token_urlsafe(32)
        runner.previous_token_hash = self._hash_token(provided)
        runner.previous_token_expires_at = now + self.token_grace_duration
        runner.token_hash = self._hash_token(access_token)
        runner.token_issued_at = now
        runner.token_expires_at = now + self.token_ttl_duration
        return access_token

    @staticmethod
    def _redact_labels(labels: dict[str, str]) -> dict[str, str]:
        return {
            key: "[REDACTED]"
            if any(part in key.lower() for part in _SENSITIVE_LABEL_PARTS)
            else value
            for key, value in labels.items()
        }
