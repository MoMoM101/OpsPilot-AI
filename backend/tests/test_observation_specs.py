from uuid import uuid4

import pytest

from app.domain.runner_tasks import RunnerReadOperation
from app.services.observation_specs import (
    ObservationSpecError,
    TrustedObservationSpecCompiler,
)


def test_compiler_builds_task_only_from_trusted_resource_configuration() -> None:
    incident_id = uuid4()
    plan_step_id = uuid4()
    resource_id = uuid4()

    task = TrustedObservationSpecCompiler().compile(
        incident_id=incident_id,
        plan_step_id=plan_step_id,
        resource_id=resource_id,
        resource_attributes={
            "observability": {
                "runnerOperations": {
                    "http.probe": {
                        "parameters": {
                            "url": "http://rag-api:8000/ready",
                            "expectedStatuses": [200],
                            "captureBody": True,
                        },
                        "timeoutSeconds": 10,
                        "maxAttempts": 2,
                    }
                }
            }
        },
        operation=RunnerReadOperation.HTTP_PROBE,
        idempotency_key="agent-observation-node-0001",
    )

    assert task.incident_id == incident_id
    assert task.plan_step_id == plan_step_id
    assert task.resource_id == resource_id
    assert task.connector == "http"
    assert task.operation == RunnerReadOperation.HTTP_PROBE
    assert task.parameters["url"] == "http://rag-api:8000/ready"
    assert task.timeout_seconds == 10
    assert task.max_attempts == 2


def test_compiler_rejects_operation_missing_from_trusted_resource_map() -> None:
    with pytest.raises(ObservationSpecError, match="not configured"):
        TrustedObservationSpecCompiler().compile(
            incident_id=uuid4(),
            plan_step_id=uuid4(),
            resource_id=uuid4(),
            resource_attributes={"observability": {"runnerOperations": {}}},
            operation=RunnerReadOperation.HTTP_PROBE,
            idempotency_key="agent-observation-node-0002",
        )


def test_compiler_reuses_runner_task_validation_for_trusted_parameters() -> None:
    with pytest.raises(ObservationSpecError, match="configuration is invalid"):
        TrustedObservationSpecCompiler().compile(
            incident_id=uuid4(),
            plan_step_id=uuid4(),
            resource_id=uuid4(),
            resource_attributes={
                "observability": {
                    "runnerOperations": {
                        "http.probe": {
                            "parameters": {
                                "url": "http://rag-api:8000/ready?token=secret"
                            }
                        }
                    }
                }
            },
            operation=RunnerReadOperation.HTTP_PROBE,
            idempotency_key="agent-observation-node-0003",
        )
