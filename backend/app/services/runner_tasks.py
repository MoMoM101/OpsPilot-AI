import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.plans import PlanStatus, PlanStepStatus, PlanStepType
from app.domain.runner_tasks import RunnerTaskStatus
from app.services.action_verifications import ActionVerificationService
from app.services.events import EventRecorder
from app.services.runners import RunnerService
from app.storage.models import EvidenceRecord, RunnerRecord, RunnerTaskRecord
from app.storage.repositories import (
    EvidenceRepository,
    IncidentRepository,
    InvestigationRepository,
    PlanRepository,
    ResourceRepository,
    RunnerRepository,
    RunnerTaskRepository,
)
from app.storage.transactions import commit_session

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:password|secret|token|api[_-]?key)\s*[:=]\s*)[^\s,;]+"),
)


class RunnerTaskService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        runner_lease_seconds: int,
        task_lease_seconds: int,
        max_output_bytes: int,
        runner_token_rotation_seconds: int = 86400,
        runner_token_ttl_seconds: int = 604800,
        runner_token_grace_seconds: int = 600,
    ) -> None:
        self.session = session
        self.task_lease_duration = timedelta(seconds=task_lease_seconds)
        self.runner_lease_seconds = runner_lease_seconds
        self.max_output_bytes = max_output_bytes
        self.tasks = RunnerTaskRepository(session)
        self.runners = RunnerRepository(session)
        self.incidents = IncidentRepository(session)
        self.resources = ResourceRepository(session)
        self.evidence = EvidenceRepository(session)
        self.plans = PlanRepository(session)
        self.investigations = InvestigationRepository(session)
        self.events = EventRecorder(session)
        self.runner_service = RunnerService(
            session,
            runner_lease_seconds,
            token_rotation_seconds=runner_token_rotation_seconds,
            token_ttl_seconds=runner_token_ttl_seconds,
            token_grace_seconds=runner_token_grace_seconds,
        )

    async def create(
        self,
        *,
        incident_id: UUID,
        plan_step_id: UUID | None,
        resource_id: UUID,
        runner_id: UUID | None,
        connector: str,
        operation: str,
        parameters: dict[str, Any],
        idempotency_key: str,
        timeout_seconds: int,
        max_attempts: int,
        commit: bool = True,
    ) -> RunnerTaskRecord:
        existing = await self.tasks.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            matches = (
                existing.incident_id == incident_id
                and existing.plan_step_id == plan_step_id
                and existing.resource_id == resource_id
                and existing.runner_id == runner_id
                and existing.connector == connector
                and existing.operation == operation
                and existing.parameters == parameters
            )
            if not matches:
                raise ApplicationError(
                    "TASK_IDEMPOTENCY_CONFLICT",
                    "Idempotency key is already used by a different task",
                    409,
                )
            return existing

        incident = await self.incidents.get(incident_id, for_update=True)
        if incident is None:
            raise ApplicationError("INCIDENT_NOT_FOUND", "Incident does not exist", 404)
        resource = await self.resources.get(resource_id)
        if resource is None:
            raise ApplicationError("RESOURCE_NOT_FOUND", "Resource does not exist", 404)
        if incident.resource_id != resource_id:
            raise ApplicationError(
                "TASK_RESOURCE_OUT_OF_SCOPE",
                "Task resource is outside the incident scope",
                409,
            )
        current_plan = await self.plans.get_latest(incident_id)
        if (
            current_plan is not None
            and current_plan.status == PlanStatus.ACTIVE
            and plan_step_id is None
        ):
            raise ApplicationError(
                "TASK_PLAN_STEP_REQUIRED",
                "Runner tasks for an active plan must reference a plan step",
                409,
            )
        if plan_step_id is not None:
            await self._validate_plan_step(
                incident_id,
                plan_step_id,
                resource_id,
                resource.name,
                operation,
            )
            if incident.tool_budget_used >= incident.tool_budget_limit:
                raise ApplicationError(
                    "TOOL_BUDGET_EXHAUSTED",
                    "Incident tool-call budget is exhausted",
                    409,
                )
        if runner_id is not None:
            runner = await self.runners.get(runner_id)
            if runner is None:
                raise ApplicationError("RUNNER_NOT_FOUND", "Runner does not exist", 404)
            self._ensure_runner_can_execute(runner, connector, operation, resource.environment_id)

        now = datetime.now(UTC)
        task = await self.tasks.create(
            incident_id=incident_id,
            plan_step_id=plan_step_id,
            resource_id=resource_id,
            runner_id=runner_id,
            connector=connector,
            operation=operation,
            parameters=parameters,
            status=RunnerTaskStatus.QUEUED,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            attempt=0,
        )
        if plan_step_id is not None:
            incident.tool_budget_used += 1
            incident.version += 1
            incident.updated_at = now
        await self.events.record(
            incident,
            "runner_task.queued",
            now,
            "control_plane",
            {
                "taskId": str(task.id),
                "planStepId": str(plan_step_id) if plan_step_id else None,
                "operation": operation,
                "toolBudgetUsed": incident.tool_budget_used,
                "toolBudgetLimit": incident.tool_budget_limit,
            },
            aggregate_type="runner_task",
            aggregate_id=task.id,
            aggregate_version=1,
        )
        if commit:
            await commit_session(self.session)
        return task

    async def claim(
        self,
        *,
        runner_id: UUID,
        access_token: str,
        runner_fencing_token: int,
    ) -> RunnerTaskRecord | None:
        runner, runner_lease = await self.runner_service.authorize(runner_id, access_token)
        if runner_lease.fencing_token != runner_fencing_token:
            raise ApplicationError(
                "STALE_RUNNER_FENCING_TOKEN",
                "Runner fencing token is stale",
                409,
            )
        now = datetime.now(UTC)
        await self._recover_expired(now)
        active = await self.tasks.get_active_for_runner(runner_id)
        if active is not None:
            return active

        for task in await self.tasks.queued_candidates(runner_id):
            resource = await self.resources.get(task.resource_id)
            if resource is None:
                continue
            if not self._runner_can_execute(
                runner,
                task.connector,
                task.operation,
                resource.environment_id,
            ):
                continue
            task.runner_id = runner_id
            task.status = RunnerTaskStatus.LEASED
            task.attempt += 1
            task.task_fencing_token = runner_fencing_token
            task.lease_expires_at = now + self.task_lease_duration
            task.updated_at = now
            await ActionVerificationService(self.session).mark_running(task, now)
            incident = await self.incidents.get(task.incident_id)
            if incident is not None:
                await self.events.record(
                    incident,
                    "runner_task.leased",
                    now,
                    "runner",
                    {"taskId": str(task.id), "runnerId": str(runner_id)},
                    aggregate_type="runner_task",
                    aggregate_id=task.id,
                    aggregate_version=task.attempt + 1,
                )
            await commit_session(self.session)
            return task
        await commit_session(self.session)
        return None

    async def renew(
        self,
        *,
        runner_id: UUID,
        task_id: UUID,
        access_token: str,
        task_fencing_token: int,
    ) -> RunnerTaskRecord:
        await self.runner_service.authorize(runner_id, access_token)
        task = await self._leased_task(runner_id, task_id, task_fencing_token)
        now = datetime.now(UTC)
        if task.lease_expires_at is None or self._as_utc(task.lease_expires_at) <= now:
            raise ApplicationError("TASK_LEASE_EXPIRED", "Task lease has expired", 409)
        task.lease_expires_at = now + self.task_lease_duration
        task.updated_at = now
        await commit_session(self.session)
        return task

    async def complete(
        self,
        *,
        runner_id: UUID,
        task_id: UUID,
        access_token: str,
        completion_id: UUID,
        task_fencing_token: int,
        succeeded: bool,
        summary: str,
        output: str,
        redacted: bool,
        output_truncated: bool,
        error_code: str | None,
    ) -> tuple[RunnerTaskRecord, bool]:
        await self.runner_service.authorize(runner_id, access_token)
        task = await self.tasks.get(task_id, for_update=True)
        if task is None:
            raise ApplicationError("RUNNER_TASK_NOT_FOUND", "Runner task does not exist", 404)
        if task.last_completion_id == completion_id:
            return task, True
        if task.status != RunnerTaskStatus.LEASED:
            raise ApplicationError("RUNNER_TASK_NOT_LEASED", "Runner task is not leased", 409)
        self._verify_task_owner(task, runner_id, task_fencing_token)
        now = datetime.now(UTC)
        if task.lease_expires_at is None or self._as_utc(task.lease_expires_at) <= now:
            raise ApplicationError("TASK_LEASE_EXPIRED", "Task lease has expired", 409)

        safe_output, server_redacted = self._redact(output)
        content_hash = hashlib.sha256(output.encode()).hexdigest()
        stored_output, truncated = self._truncate(safe_output)
        task.status = RunnerTaskStatus.SUCCEEDED if succeeded else RunnerTaskStatus.FAILED
        task.last_completion_id = completion_id
        task.result_summary = summary
        task.error_code = error_code
        task.output_truncated = truncated or output_truncated
        task.completed_at = now
        task.updated_at = now
        task.lease_expires_at = None

        observation_wait = await self.investigations.get_waiting_observation_for_task(task.id)
        if succeeded or observation_wait is not None:
            evidence = await self._create_evidence(
                task=task,
                source=f"runner:{runner_id}:{task.connector}",
                summary=summary,
                content_hash=content_hash,
                stored_output=stored_output,
                redacted=redacted or server_redacted,
                collection_status="succeeded" if succeeded else "failed",
                now=now,
            )
            task.evidence_id = evidence.id

        if task.evidence_id is not None and task.plan_step_id is not None:
            step = await self.plans.get_step_for_incident(
                task.incident_id,
                task.plan_step_id,
                for_update=True,
            )
            if step is not None:
                evidence_id = str(task.evidence_id)
                if evidence_id not in step.evidence_ids:
                    step.evidence_ids = [*step.evidence_ids, evidence_id]
                    step.version += 1
                    step.updated_at = now

        await ActionVerificationService(self.session).finalize_task(
            task,
            succeeded=succeeded,
            now=now,
        )
        if observation_wait is not None:
            from app.services.investigation_observations import (
                InvestigationObservationService,
            )

            await InvestigationObservationService(
                self.session,
                runner_lease_seconds=self.runner_lease_seconds,
                task_lease_seconds=int(self.task_lease_duration.total_seconds()),
                max_output_bytes=self.max_output_bytes,
            ).resolve_task(
                runner_task_id=task.id,
                outcome="succeeded" if succeeded else "failed",
                evidence_id=task.evidence_id,
                actor="runner",
                now=now,
            )

        incident = await self.incidents.get(task.incident_id)
        if incident is not None:
            await self.events.record(
                incident,
                "runner_task.succeeded" if succeeded else "runner_task.failed",
                now,
                "runner",
                {
                    "taskId": str(task.id),
                    "planStepId": str(task.plan_step_id) if task.plan_step_id else None,
                    "runnerId": str(runner_id),
                    "evidenceId": str(task.evidence_id) if task.evidence_id else None,
                    "outputTruncated": task.output_truncated,
                    "errorCode": error_code,
                },
                aggregate_type="runner_task",
                aggregate_id=task.id,
                aggregate_version=task.attempt + 2,
            )
        await commit_session(self.session)
        return task, False

    async def list(
        self,
        limit: int,
        offset: int,
        status: RunnerTaskStatus | None,
        incident_id: UUID | None,
        runner_id: UUID | None,
        plan_step_id: UUID | None,
    ) -> tuple[list[RunnerTaskRecord], int]:
        await self._recover_expired(datetime.now(UTC))
        await commit_session(self.session)
        records = await self.tasks.list(
            limit,
            offset,
            status,
            incident_id,
            runner_id,
            plan_step_id,
        )
        total = await self.tasks.count(status, incident_id, runner_id, plan_step_id)
        return records, total

    async def _validate_plan_step(
        self,
        incident_id: UUID,
        plan_step_id: UUID,
        resource_id: UUID,
        resource_name: str,
        operation: str,
    ) -> None:
        step = await self.plans.get_step_for_incident(
            incident_id,
            plan_step_id,
            for_update=True,
        )
        if step is None:
            raise ApplicationError("PLAN_STEP_NOT_FOUND", "Plan step does not exist", 404)
        plan = await self.plans.get(step.plan_id)
        if plan is None or plan.status != PlanStatus.ACTIVE:
            raise ApplicationError(
                "PLAN_NOT_ACTIVE",
                "Runner tasks require a step in the active plan",
                409,
            )
        if step.status != PlanStepStatus.RUNNING:
            raise ApplicationError(
                "PLAN_STEP_NOT_RUNNING",
                "Runner tasks can only be created for a running plan step",
                409,
            )
        if step.step_type not in {
            PlanStepType.OBSERVE,
            PlanStepType.ANALYZE,
            PlanStepType.EXPERIMENT,
            PlanStepType.VERIFY,
        }:
            raise ApplicationError(
                "PLAN_STEP_NOT_OBSERVATIONAL",
                "Read-only Runner tasks are not allowed for this step type",
                409,
            )
        if operation not in step.allowed_capabilities:
            raise ApplicationError(
                "PLAN_STEP_CAPABILITY_DENIED",
                "Runner operation is not allowlisted by the plan step",
                409,
            )
        if step.resource_scope and not {
            str(resource_id),
            resource_name,
        }.intersection(step.resource_scope):
            raise ApplicationError(
                "PLAN_STEP_RESOURCE_OUT_OF_SCOPE",
                "Runner task resource is outside the plan step scope",
                409,
            )

    async def _recover_expired(self, now: datetime) -> None:
        for task in await self.tasks.expired_leases(now):
            task.lease_expires_at = None
            task.task_fencing_token = None
            task.updated_at = now
            if task.attempt < task.max_attempts:
                task.status = RunnerTaskStatus.QUEUED
            else:
                task.status = RunnerTaskStatus.FAILED
                task.error_code = "TASK_LEASE_EXPIRED"
                task.result_summary = "Runner task lease expired"
                task.completed_at = now
                observation_wait = (
                    await self.investigations.get_waiting_observation_for_task(task.id)
                )
                if observation_wait is not None:
                    evidence = await self._create_evidence(
                        task=task,
                        source=f"runner:control-plane:{task.connector}",
                        summary=task.result_summary,
                        content_hash=hashlib.sha256(b"").hexdigest(),
                        stored_output="",
                        redacted=False,
                        collection_status="failed",
                        now=now,
                    )
                    task.evidence_id = evidence.id
                    from app.services.investigation_observations import (
                        InvestigationObservationService,
                    )

                    await InvestigationObservationService(
                        self.session,
                        runner_lease_seconds=self.runner_lease_seconds,
                        task_lease_seconds=int(self.task_lease_duration.total_seconds()),
                        max_output_bytes=self.max_output_bytes,
                    ).resolve_task(
                        runner_task_id=task.id,
                        outcome="failed",
                        evidence_id=evidence.id,
                        actor="control_plane",
                        now=now,
                    )
                await ActionVerificationService(self.session).finalize_task(
                    task,
                    succeeded=False,
                    now=now,
                )

    async def _create_evidence(
        self,
        *,
        task: RunnerTaskRecord,
        source: str,
        summary: str,
        content_hash: str,
        stored_output: str,
        redacted: bool,
        collection_status: str,
        now: datetime,
    ) -> EvidenceRecord:
        observed_from, observed_to, time_confidence = self._observation_metadata(task, now)
        return await self.evidence.create(
            incident_id=task.incident_id,
            resource_id=task.resource_id,
            evidence_type="runner_observation",
            source=source,
            summary=summary,
            content_hash=content_hash,
            redacted=redacted,
            observed_from=observed_from,
            observed_to=observed_to,
            collected_at=now,
            collection_status=collection_status,
            time_confidence=time_confidence,
            data={
                "resourceId": str(task.resource_id),
                "taskId": str(task.id),
                "planStepId": str(task.plan_step_id) if task.plan_step_id else None,
                "operation": task.operation,
                "content": stored_output,
                "outputTruncated": task.output_truncated,
                "collectionStatus": collection_status,
                "errorCode": task.error_code,
                "collectedAt": now.isoformat(),
            },
        )

    async def _leased_task(
        self,
        runner_id: UUID,
        task_id: UUID,
        task_fencing_token: int,
    ) -> RunnerTaskRecord:
        task = await self.tasks.get(task_id, for_update=True)
        if task is None:
            raise ApplicationError("RUNNER_TASK_NOT_FOUND", "Runner task does not exist", 404)
        if task.status != RunnerTaskStatus.LEASED:
            raise ApplicationError("RUNNER_TASK_NOT_LEASED", "Runner task is not leased", 409)
        self._verify_task_owner(task, runner_id, task_fencing_token)
        return task

    @staticmethod
    def _verify_task_owner(
        task: RunnerTaskRecord,
        runner_id: UUID,
        task_fencing_token: int,
    ) -> None:
        if task.runner_id != runner_id or task.task_fencing_token != task_fencing_token:
            raise ApplicationError(
                "STALE_TASK_FENCING_TOKEN",
                "Task lease ownership or fencing token is stale",
                409,
            )

    @staticmethod
    def _runner_can_execute(
        runner: RunnerRecord,
        connector: str,
        operation: str,
        environment_id: UUID,
    ) -> bool:
        if runner.environment_id is not None and runner.environment_id != environment_id:
            return False
        connectors = runner.capabilities.get("connectors", [])
        if not isinstance(connectors, list):
            return False
        for capability in connectors:
            if not isinstance(capability, dict) or capability.get("connector") != connector:
                continue
            observe = capability.get("observe", [])
            return isinstance(observe, list) and operation in observe
        return False

    def _ensure_runner_can_execute(
        self,
        runner: RunnerRecord,
        connector: str,
        operation: str,
        environment_id: UUID,
    ) -> None:
        if not self._runner_can_execute(runner, connector, operation, environment_id):
            raise ApplicationError(
                "RUNNER_CAPABILITY_MISMATCH",
                "Runner cannot execute this read-only operation in the resource environment",
                409,
            )

    def _truncate(self, value: str) -> tuple[str, bool]:
        encoded = value.encode()
        if len(encoded) <= self.max_output_bytes:
            return value, False
        return encoded[: self.max_output_bytes].decode(errors="ignore"), True

    @staticmethod
    def _redact(value: str) -> tuple[str, bool]:
        result = value
        for pattern in _SECRET_PATTERNS:
            result = pattern.sub(r"\1[REDACTED]", result)
        return result, result != value

    @staticmethod
    def _observation_metadata(
        task: RunnerTaskRecord,
        collected_at: datetime,
    ) -> tuple[datetime | None, datetime, str]:
        if task.operation == "prometheus.query_range":
            start = task.parameters.get("start")
            end = task.parameters.get("end")
            if isinstance(start, str) and isinstance(end, str):
                return (
                    datetime.fromisoformat(start.replace("Z", "+00:00")),
                    datetime.fromisoformat(end.replace("Z", "+00:00")),
                    "source_timestamp",
                )
        if task.operation == "prometheus.query":
            query_time = task.parameters.get("time")
            if isinstance(query_time, str):
                parsed = datetime.fromisoformat(query_time.replace("Z", "+00:00"))
                return parsed, parsed, "source_timestamp"
        if task.operation == "journal.query":
            since_minutes = task.parameters.get("sinceMinutes", 30)
            if isinstance(since_minutes, int) and not isinstance(since_minutes, bool):
                return (
                    collected_at - timedelta(minutes=since_minutes),
                    collected_at,
                    "source_timestamp",
                )
        return None, collected_at, "runner_reported"

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
