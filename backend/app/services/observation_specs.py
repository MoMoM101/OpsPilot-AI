from typing import Any
from uuid import UUID

from app.domain.runner_tasks import RunnerReadOperation
from app.schemas.runner_tasks import RunnerTaskCreate


class ObservationSpecError(RuntimeError):
    pass


class TrustedObservationSpecCompiler:
    """Compile an Agent selection into a task using only trusted Resource attributes."""

    def compile(
        self,
        *,
        incident_id: UUID,
        plan_step_id: UUID,
        resource_id: UUID,
        resource_attributes: dict[str, Any],
        operation: RunnerReadOperation,
        idempotency_key: str,
    ) -> RunnerTaskCreate:
        observability = resource_attributes.get("observability")
        if not isinstance(observability, dict):
            raise ObservationSpecError("Resource has no trusted observability configuration")
        operations = observability.get("runnerOperations")
        if not isinstance(operations, dict):
            raise ObservationSpecError("Resource has no trusted Runner operation map")
        raw_spec = operations.get(operation.value)
        if not isinstance(raw_spec, dict):
            raise ObservationSpecError("Requested operation is not configured for this Resource")

        parameters = raw_spec.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ObservationSpecError("Trusted Runner operation parameters must be an object")
        timeout_seconds = raw_spec.get("timeoutSeconds", 30)
        max_attempts = raw_spec.get("maxAttempts", 1)

        try:
            return RunnerTaskCreate(
                incident_id=incident_id,
                plan_step_id=plan_step_id,
                resource_id=resource_id,
                connector=operation.value.partition(".")[0],
                operation=operation,
                parameters=dict(parameters),
                idempotency_key=idempotency_key,
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
            )
        except (TypeError, ValueError) as exc:
            raise ObservationSpecError(
                "Trusted Runner operation configuration is invalid"
            ) from exc
