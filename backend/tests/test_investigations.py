import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.application import create_app
from app.core.config import Settings
from app.services.agent_node_handler import ProviderBackedAgentNodeHandler
from app.services.agent_provider import (
    ActionProposal,
    ActionProposalOutput,
    HypothesisProposal,
    InvestigatorOutput,
    ObservationProposal,
    ObservationProposalOutput,
    PlannerOutput,
    PlanStepProposal,
    ProviderResult,
    ReplannerOutput,
)
from app.services.agent_runtime import (
    AgentNodeContext,
    AgentNodeOutcome,
    AgentRuntimeWorker,
)
from app.services.investigations import InvestigationService
from app.storage import Base
from app.storage.models import InvestigationObservationWaitRecord
from app.storage.repositories import InvestigationRepository


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(app) as test_client:
        yield test_client


def _investigating_incident(client: TestClient) -> dict[str, object]:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "Investigation runtime", "slug": "investigation-runtime"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "runtime-test-service",
            "kind": "service",
            "attributes": {
                "observability": {
                    "runnerOperations": {
                        "http.probe": {
                            "parameters": {
                                "url": "http://runtime-test-service:8000/ready",
                                "expectedStatuses": [200],
                            },
                            "timeoutSeconds": 10,
                        }
                    }
                }
            },
        },
    ).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "title": "Runtime checkpoint test",
            "severity": "high",
            "resourceId": resource["id"],
        },
    ).json()
    for target in ("CORRELATING", "INVESTIGATING"):
        incident = client.post(
            f"/api/v1/incidents/{incident['id']}/transitions",
            json={"target": target, "expectedVersion": incident["version"]},
        ).json()
    incident["_environmentId"] = environment["id"]
    return incident


def test_hitl_approval_wait_resolves_and_requeues_atomically(client: TestClient) -> None:
    incident = _investigating_incident(client)
    policy = client.post(
        "/api/v1/policies",
        json={
            "environmentId": incident["_environmentId"],
            "name": "HITL restart approval",
            "effect": "allow",
            "capabilities": ["container.restart"],
            "resourceIds": [incident["resourceId"]],
            "approvalRequired": True,
        },
    )
    assert policy.status_code == 201
    snapshot = client.post(
        "/api/v1/policies/evaluate",
        json={
            "environmentId": incident["_environmentId"],
            "incidentId": incident["id"],
            "resourceId": incident["resourceId"],
            "capability": "container.restart",
            "autonomyLevel": "L2",
            "risk": "medium",
        },
    ).json()
    approval = client.post(
        "/api/v1/approvals",
        json={"policyDecisionId": snapshot["snapshotId"]},
    ).json()
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={"idempotencyKey": "investigation-hitl-approval-001"},
    ).json()
    running = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/transitions",
        json={"target": "running", "expectedVersion": run["version"]},
    ).json()
    checkpoint = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/checkpoints",
        json={
            "nodeExecutionId": "hitl-approval-checkpoint-001",
            "expectedRunVersion": running["version"],
            "node": "run_investigator",
            "iteration": 0,
            "completedNodeKeys": ["run_investigator:0"],
            "nextAction": "pause",
            "outputSummary": "Waiting for an approved bounded restart",
        },
    ).json()
    wait_response = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/hitl-waits",
        json={
            "checkpointId": checkpoint["checkpoint"]["id"],
            "subjectType": "approval",
            "subjectId": approval["id"],
            "expectedRunVersion": checkpoint["runVersion"],
        },
    )
    assert wait_response.status_code == 200
    wait = wait_response.json()["wait"]
    assert wait["status"] == "waiting"
    assert client.get(f"/api/v1/investigation-runs/{run['id']}").json()["status"] == "paused"

    duplicate = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/hitl-waits",
        json={
            "checkpointId": checkpoint["checkpoint"]["id"],
            "subjectType": "approval",
            "subjectId": approval["id"],
            "expectedRunVersion": checkpoint["runVersion"],
        },
    ).json()
    assert duplicate["duplicate"] is True

    decision = client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        json={"decision": "reject", "expectedVersion": approval["version"]},
    )
    assert decision.status_code == 200
    resumed_run = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert resumed_run["status"] == "queued"
    listed_response = client.get(f"/api/v1/investigation-runs/{run['id']}/hitl-waits")
    assert listed_response.headers["X-Total-Count"] == "1"
    assert listed_response.headers["X-Limit"] == "100"
    assert listed_response.headers["X-Offset"] == "0"
    listed = listed_response.json()
    assert listed[0]["status"] == "resolved"
    assert listed[0]["outcome"] == "rejected"

    async def claim_resumed() -> None:
        async with client.app.state.database.session_factory() as session:
            claimed = await InvestigationService(session).claim_next_runtime_run(
                owner="hitl-resume-worker", lease_seconds=60
            )
            assert claimed is not None
            assert claimed.id == UUID(str(run["id"]))

    asyncio.run(claim_resumed())
    listed = client.get(f"/api/v1/investigation-runs/{run['id']}/hitl-waits").json()
    assert listed[0]["resumedAt"] is not None
    stream = client.get(f"/api/v1/incidents/{incident['id']}/stream", params={"follow": "false"})
    assert "event: investigation.hitl_wait_started" in stream.text
    assert "event: investigation.hitl_wait_resolved" in stream.text


def test_investigation_run_checkpoint_idempotency_and_lifecycle(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident = _investigating_incident(client)
    graphs = client.get("/api/v1/investigation-graphs")
    assert graphs.status_code == 200
    assert [graph["version"] for graph in graphs.json()] == ["graph-v1", "graph-v2"]
    graph = client.get("/api/v1/investigation-graphs/graph-v1").json()
    assert graph["entryNode"] == "load_incident"
    assert [node["key"] for node in graph["nodes"]] == [
        "load_incident",
        "load_topology",
        "load_recent_changes",
        "classify_complexity",
        "create_plan",
        "select_next_step",
        "run_investigator",
        "assess_evidence",
        "maybe_replan",
        "escalate_or_finish",
    ]
    missing_graph = client.get("/api/v1/investigation-graphs/graph-v0")
    assert missing_graph.status_code == 404
    assert missing_graph.json()["error"]["code"] == "INVESTIGATION_GRAPH_VERSION_UNAVAILABLE"
    unsupported_run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={
            "idempotencyKey": "investigation-run-unsupported-001",
            "graphVersion": "graph-v0",
        },
    )
    assert unsupported_run.status_code == 422
    assert unsupported_run.json()["error"]["code"] == "INVESTIGATION_GRAPH_VERSION_UNAVAILABLE"
    hypothesis = client.post(
        f"/api/v1/incidents/{incident['id']}/hypotheses",
        json={"summary": "Dependency latency is elevated", "confidence": 65},
    ).json()
    plan = client.post(
        f"/api/v1/incidents/{incident['id']}/plans",
        json={
            "objective": "Identify the slow dependency",
            "steps": [
                {
                    "title": "Collect dependency health",
                    "objective": "Collect bounded evidence",
                    "kind": "observe",
                    "risk": "read_only",
                }
            ],
        },
    ).json()
    step = plan["steps"][0]

    create_payload = {
        "idempotencyKey": "investigation-run-runtime-001",
        "graphVersion": "graph-v1",
        "maxIterations": 5,
    }
    created_response = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json=create_payload,
    )
    assert created_response.status_code == 201
    run = created_response.json()
    assert run["status"] == "queued"
    assert run["threadId"]
    assert run["version"] == 1

    duplicate = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json=create_payload,
    ).json()
    assert duplicate["id"] == run["id"]
    assert duplicate["threadId"] == run["threadId"]

    active_conflict = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={**create_payload, "idempotencyKey": "investigation-run-runtime-002"},
    )
    assert active_conflict.status_code == 409
    assert active_conflict.json()["error"]["code"] == "ACTIVE_INVESTIGATION_RUN_EXISTS"

    running = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/transitions",
        json={"target": "running", "expectedVersion": run["version"]},
    ).json()
    assert running["status"] == "running"
    assert running["startedAt"] is not None

    unknown_node = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/checkpoints",
        json={
            "nodeExecutionId": "node-execution-unknown-001",
            "expectedRunVersion": running["version"],
            "node": "unknown_node",
            "iteration": 0,
        },
    )
    assert unknown_node.status_code == 422
    assert unknown_node.json()["error"]["code"] == "INVESTIGATION_GRAPH_NODE_NOT_FOUND"

    invalid_completed_key = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/checkpoints",
        json={
            "nodeExecutionId": "node-execution-invalid-key-001",
            "expectedRunVersion": running["version"],
            "node": "load_incident",
            "iteration": 0,
            "completedNodeKeys": ["unknown_node:0"],
        },
    )
    assert invalid_completed_key.status_code == 422
    assert invalid_completed_key.json()["error"]["code"] == "INVALID_COMPLETED_NODE_KEY"

    node_execution_id = "node-execution-load-incident-001"
    checkpoint_payload = {
        "nodeExecutionId": node_execution_id,
        "expectedRunVersion": running["version"],
        "node": "load_incident",
        "iteration": 0,
        "planStepId": step["id"],
        "hypothesisIds": [hypothesis["id"]],
        "completedNodeKeys": ["load_incident:0"],
        "modelRequests": 1,
        "modelInputTokens": 120,
        "modelOutputTokens": 30,
        "outputSummary": "Incident context loaded by reference",
    }
    checkpoint_response = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/checkpoints",
        json=checkpoint_payload,
    )
    assert checkpoint_response.status_code == 200
    written = checkpoint_response.json()
    assert written["duplicate"] is False
    assert written["checkpoint"]["sequence"] == 1
    assert written["checkpoint"]["graphVersion"] == "graph-v1"
    assert written["runVersion"] == running["version"] + 1
    assert written["checkpoint"]["modelRequests"] == 1

    replay = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/checkpoints",
        json=checkpoint_payload,
    ).json()
    assert replay["duplicate"] is True
    assert replay["checkpoint"]["id"] == written["checkpoint"]["id"]
    assert replay["runVersion"] == written["runVersion"]

    conflicting_replay = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/checkpoints",
        json={**checkpoint_payload, "node": "load_topology"},
    )
    assert conflicting_replay.status_code == 409
    assert conflicting_replay.json()["error"]["code"] == "CHECKPOINT_IDEMPOTENCY_CONFLICT"

    unknown_evidence = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/checkpoints",
        json={
            "nodeExecutionId": "node-execution-evidence-001",
            "expectedRunVersion": written["runVersion"],
            "node": "assess_evidence",
            "iteration": 1,
            "evidenceIds": [str(uuid4())],
        },
    )
    assert unknown_evidence.status_code == 422
    assert unknown_evidence.json()["error"]["code"] == "CHECKPOINT_EVIDENCE_NOT_FOUND"

    second_checkpoint = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/checkpoints",
        json={
            "nodeExecutionId": "node-execution-select-step-001",
            "expectedRunVersion": written["runVersion"],
            "node": "select_next_step",
            "iteration": 1,
            "planStepId": step["id"],
            "hypothesisIds": [hypothesis["id"]],
            "completedNodeKeys": ["load_incident:0", "select_next_step:1"],
        },
    ).json()
    assert second_checkpoint["checkpoint"]["sequence"] == 2

    paused = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/transitions",
        json={"target": "paused", "expectedVersion": second_checkpoint["runVersion"]},
    ).json()
    resumed = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/transitions",
        json={"target": "running", "expectedVersion": paused["version"]},
    ).json()
    completed = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/transitions",
        json={"target": "completed", "expectedVersion": resumed["version"]},
    ).json()
    assert completed["status"] == "completed"
    assert completed["completedAt"] is not None
    assert completed["modelRequestsUsed"] == 1
    assert completed["modelInputTokensUsed"] == 120
    assert completed["modelOutputTokensUsed"] == 30

    checkpoints = client.get(
        f"/api/v1/investigation-runs/{run['id']}/checkpoints",
        params={"after_sequence": 1},
    ).json()
    assert [item["sequence"] for item in checkpoints] == [2]
    runs_response = client.get(
        f"/api/v1/incidents/{incident['id']}/investigation-runs"
    )
    assert runs_response.headers["X-Total-Count"] == "1"
    assert runs_response.headers["X-Limit"] == "50"
    assert runs_response.headers["X-Offset"] == "0"
    runs = runs_response.json()
    assert [item["id"] for item in runs] == [run["id"]]

    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert "event: investigation.run_created" in stream.text
    assert "event: investigation.checkpointed" in stream.text
    assert "event: investigation.status_changed" in stream.text

    replacement = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={**create_payload, "idempotencyKey": "investigation-run-runtime-003"},
    )
    assert replacement.status_code == 201
    replacement_run = replacement.json()
    assert replacement_run["threadId"] != run["threadId"]
    replacement_running = client.post(
        f"/internal/v1/investigation-runs/{replacement_run['id']}/transitions",
        json={"target": "running", "expectedVersion": replacement_run["version"]},
    ).json()
    replacement_paused = client.post(
        f"/internal/v1/investigation-runs/{replacement_run['id']}/transitions",
        json={"target": "paused", "expectedVersion": replacement_running["version"]},
    ).json()
    monkeypatch.setattr(
        "app.services.investigations.get_investigation_graph",
        lambda _version: None,
    )
    incompatible_resume = client.post(
        f"/internal/v1/investigation-runs/{replacement_run['id']}/transitions",
        json={"target": "running", "expectedVersion": replacement_paused["version"]},
    )
    assert incompatible_resume.status_code == 409
    assert incompatible_resume.json()["error"]["code"] == "INVESTIGATION_GRAPH_VERSION_UNAVAILABLE"


class _FinishingNodeHandler:
    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute(self, context: AgentNodeContext) -> AgentNodeOutcome:
        self.executed.append(f"{context.node}:{context.iteration}")
        if context.node == "maybe_replan":
            return AgentNodeOutcome("Investigation can finish", next_action="finish")
        return AgentNodeOutcome(f"Completed {context.node}")


class _NoProgressNodeHandler:
    async def execute(self, context: AgentNodeContext) -> AgentNodeOutcome:
        if context.node == "maybe_replan":
            return AgentNodeOutcome(
                "No new evidence was produced",
                progressed=False,
                next_action="continue",
            )
        return AgentNodeOutcome(f"Completed {context.node}")


class _ContinuingNodeHandler:
    async def execute(self, context: AgentNodeContext) -> AgentNodeOutcome:
        if context.node == "maybe_replan":
            return AgentNodeOutcome("Another iteration is needed", next_action="continue")
        return AgentNodeOutcome(f"Completed {context.node}")


class _StructuredProviderStub:
    def __init__(self, resource_id: str) -> None:
        self.resource_id = resource_id

    async def plan(self, _prompt: str, *, request_limit: int | None = None):
        return ProviderResult(
            PlannerOutput(
                objective="Verify service health",
                steps=[
                    PlanStepProposal(
                        title="Probe service",
                        objective="Collect bounded health evidence",
                        kind="observe",
                        resource_scope=[self.resource_id],
                        allowed_capabilities=["http.probe"],
                    )
                ],
                max_tool_calls=3,
                max_duration_seconds=300,
                summary="Created a bounded read-only plan",
            ),
            requests=1,
            input_tokens=100,
            output_tokens=40,
        )

    async def investigate(self, _prompt: str, *, request_limit: int | None = None):
        return ProviderResult(
            InvestigatorOutput(
                hypotheses=[
                    HypothesisProposal(summary="Service health is degraded", confidence=60)
                ],
                progressed=True,
                summary="Created a hypothesis from bounded context",
            ),
            requests=1,
            input_tokens=80,
            output_tokens=30,
        )

    async def observe(self, _prompt: str, *, request_limit: int | None = None):
        return ProviderResult(
            ObservationProposalOutput(
                action="observe",
                proposal=ObservationProposal(
                    resource_id=self.resource_id,
                    operation="http.probe",
                    purpose="Check business readiness through a trusted endpoint",
                ),
                reason="A fresh readiness observation is required",
            ),
            requests=1,
            input_tokens=60,
            output_tokens=20,
        )

    async def replan(self, _prompt: str, *, request_limit: int | None = None):
        return ProviderResult(
            ReplannerOutput(action="finish", progressed=True, reason="Enough evidence"),
            requests=1,
            input_tokens=50,
            output_tokens=10,
        )


class _ActionProviderStub(_StructuredProviderStub):
    last_replan_prompt: str | None = None

    async def plan(self, _prompt: str, *, request_limit: int | None = None):
        return ProviderResult(
            PlannerOutput(
                objective="Restore the unhealthy container",
                steps=[
                    PlanStepProposal(
                        title="Restart bounded container",
                        objective="Apply the approved container restart",
                        kind="remediate",
                        resource_scope=[self.resource_id],
                        allowed_capabilities=["container.restart"],
                        success_criteria=["Health check passes"],
                        risk="medium",
                    )
                ],
                summary="Prepared one policy-controlled remediation step",
            ),
            requests=1,
            input_tokens=100,
            output_tokens=40,
        )

    async def propose_action(self, _prompt: str, *, request_limit: int | None = None):
        return ProviderResult(
            ActionProposalOutput(
                action="propose",
                proposal=ActionProposal(
                    resource_id=self.resource_id,
                    capability="container.restart",
                    parameters={"containerId": "api"},
                    verification_criteria=["Health check passes"],
                    rollback_capability=None,
                    risk="medium",
                ),
                reason="Evidence supports a bounded restart",
            ),
            requests=1,
            input_tokens=60,
            output_tokens=30,
        )

    async def replan(self, prompt: str, *, request_limit: int | None = None):
        self.last_replan_prompt = prompt
        return await super().replan(prompt, request_limit=request_limit)


def test_graph_v2_action_proposal_pauses_approves_and_resumes(client: TestClient) -> None:
    incident = _investigating_incident(client)
    policy = client.post(
        "/api/v1/policies",
        json={
            "environmentId": incident["_environmentId"],
            "name": "Agent bounded restart",
            "effect": "allow",
            "autonomyLevels": ["L1"],
            "riskLevels": ["medium"],
            "capabilities": ["container.restart"],
            "resourceIds": [incident["resourceId"]],
            "approvalRequired": True,
        },
    )
    assert policy.status_code == 201
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={
            "idempotencyKey": "agent-action-proposal-001",
            "graphVersion": "graph-v2",
            "maxModelRequests": 20,
        },
    ).json()
    provider = _ActionProviderStub(incident["resourceId"])  # type: ignore[arg-type]
    handler = ProviderBackedAgentNodeHandler(
        client.app.state.database,
        provider,  # type: ignore[arg-type]
    )
    first_worker = AgentRuntimeWorker(
        client.app.state.database, handler, owner="action-proposal-worker-1"
    )
    assert asyncio.run(first_worker.run_once()) is True
    paused = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert paused["status"] == "paused"
    proposals_response = client.get(
        "/api/v1/action-proposals", params={"incident_id": incident["id"]}
    )
    assert proposals_response.headers["X-Total-Count"] == "1"
    proposals = proposals_response.json()
    assert len(proposals) == 1
    assert proposals[0]["status"] == "awaiting_approval"
    assert proposals[0]["actionRequestId"] is None
    approval_id = proposals[0]["approvalId"]
    waits = client.get(f"/api/v1/investigation-runs/{run['id']}/hitl-waits").json()
    assert waits[0]["subjectId"] == approval_id
    assert waits[0]["status"] == "waiting"
    checkpoints = client.get(f"/api/v1/investigation-runs/{run['id']}/checkpoints").json()
    action_checkpoint = next(item for item in checkpoints if item["node"] == "propose_action")
    assert action_checkpoint["planStepId"] == proposals[0]["planStepId"]

    approval = next(
        item for item in client.get("/api/v1/approvals").json() if item["id"] == approval_id
    )
    approved = client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approve", "expectedVersion": approval["version"]},
    )
    assert approved.status_code == 200
    proposals = client.get(
        "/api/v1/action-proposals", params={"incident_id": incident["id"]}
    ).json()
    assert proposals[0]["status"] == "action_ready"
    assert proposals[0]["actionRequestId"] is not None
    assert client.get(f"/api/v1/investigation-runs/{run['id']}").json()["status"] == "queued"

    second_worker = AgentRuntimeWorker(
        client.app.state.database, handler, owner="action-proposal-worker-2"
    )
    assert asyncio.run(second_worker.run_once()) is True
    completed = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert completed["status"] == "completed"
    proposals = client.get(
        "/api/v1/action-proposals", params={"incident_id": incident["id"]}
    ).json()
    assert len(proposals) == 1
    assert provider.last_replan_prompt is not None
    replan_payload = json.loads(provider.last_replan_prompt)
    assert replan_payload["hitlDecision"]["outcome"] == "approved"
    assert replan_payload["hitlDecision"]["subjectId"] == approval_id


def test_observation_task_failure_creates_evidence_and_resumes_run(
    client: TestClient,
) -> None:
    incident = _investigating_incident(client)
    runner = client.post(
        "/runner/v1/runners/register",
        json={
            "name": "investigation-http-runner",
            "softwareVersion": "0.1.0",
            "environmentId": incident["_environmentId"],
            "capabilities": [
                {
                    "connector": "http",
                    "contractVersion": "1.0",
                    "observe": ["http.probe"],
                }
            ],
        },
    ).json()
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={
            "idempotencyKey": "agent-observation-failure-001",
            "graphVersion": "graph-v1",
            "maxModelRequests": 20,
        },
    ).json()
    provider = _StructuredProviderStub(incident["resourceId"])  # type: ignore[arg-type]
    handler = ProviderBackedAgentNodeHandler(
        client.app.state.database,
        provider,  # type: ignore[arg-type]
    )
    first_worker = AgentRuntimeWorker(
        client.app.state.database,
        handler,
        owner="observation-worker-1",
    )

    assert asyncio.run(first_worker.run_once()) is True
    paused = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert paused["status"] == "paused"
    tasks = client.get(
        "/api/v1/runner-tasks", params={"incident_id": incident["id"]}
    ).json()
    assert len(tasks) == 1
    assert tasks[0]["operation"] == "http.probe"
    checkpoints = client.get(
        f"/api/v1/investigation-runs/{run['id']}/checkpoints"
    ).json()
    observation_checkpoints = [
        item for item in checkpoints if item["node"] == "run_investigator"
    ]
    assert len(observation_checkpoints) == 1
    assert observation_checkpoints[0]["nextAction"] == "pause"

    authorization = {"Authorization": f"Bearer {runner['accessToken']}"}
    claimed = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/claim",
        json={"runnerFencingToken": runner["fencingToken"]},
        headers=authorization,
    ).json()["task"]
    completed = client.post(
        f"/runner/v1/runners/{runner['id']}/tasks/{claimed['id']}/complete",
        json={
            "completionId": str(uuid4()),
            "taskFencingToken": claimed["taskFencingToken"],
            "status": "failed",
            "summary": "RAG readiness endpoint returned 503",
            "output": "service unavailable",
            "errorCode": "HTTP_STATUS_MISMATCH",
        },
        headers=authorization,
    )
    assert completed.status_code == 200
    completed_task = completed.json()["task"]
    assert completed_task["status"] == "failed"
    assert completed_task["evidenceId"] is not None
    evidence = client.get(f"/api/v1/evidence/{completed_task['evidenceId']}").json()
    assert evidence["collectionStatus"] == "failed"
    assert evidence["data"]["errorCode"] == "HTTP_STATUS_MISMATCH"
    assert client.get(f"/api/v1/investigation-runs/{run['id']}").json()["status"] == "queued"

    async def read_wait() -> InvestigationObservationWaitRecord:
        async with client.app.state.database.session_factory() as session:
            wait = await session.scalar(
                select(InvestigationObservationWaitRecord).where(
                    InvestigationObservationWaitRecord.run_id == UUID(run["id"])
                )
            )
            assert wait is not None
            return wait

    wait = asyncio.run(read_wait())
    assert wait.status.value == "resolved"
    assert wait.outcome == "failed"
    assert wait.evidence_id == UUID(completed_task["evidenceId"])

    second_worker = AgentRuntimeWorker(
        client.app.state.database,
        handler,
        owner="observation-worker-2",
    )
    assert asyncio.run(second_worker.run_once()) is True
    final_run = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert final_run["status"] == "completed"
    checkpoints = client.get(
        f"/api/v1/investigation-runs/{run['id']}/checkpoints"
    ).json()
    assert len([item for item in checkpoints if item["node"] == "run_investigator"]) == 1
    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert "event: investigation.observation_wait_started" in stream.text
    assert "event: investigation.observation_wait_resolved" in stream.text


def test_cancelling_observation_run_cancels_wait_and_runner_task(
    client: TestClient,
) -> None:
    incident = _investigating_incident(client)
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={
            "idempotencyKey": "agent-observation-cancel-001",
            "graphVersion": "graph-v1",
            "maxModelRequests": 20,
        },
    ).json()
    handler = ProviderBackedAgentNodeHandler(
        client.app.state.database,
        _StructuredProviderStub(incident["resourceId"]),  # type: ignore[arg-type]
    )
    worker = AgentRuntimeWorker(
        client.app.state.database,
        handler,
        owner="observation-cancel-worker",
    )
    assert asyncio.run(worker.run_once()) is True
    paused = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert paused["status"] == "paused"

    cancelled = client.post(
        f"/api/v1/investigation-runs/{run['id']}/cancel",
        json={"expectedVersion": paused["version"]},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    task = client.get(
        "/api/v1/runner-tasks", params={"incident_id": incident["id"]}
    ).json()[0]
    assert task["status"] == "cancelled"
    assert task["errorCode"] == "INVESTIGATION_RUN_CANCELLED"

    async def read_wait() -> InvestigationObservationWaitRecord:
        async with client.app.state.database.session_factory() as session:
            wait = await session.scalar(
                select(InvestigationObservationWaitRecord).where(
                    InvestigationObservationWaitRecord.run_id == UUID(run["id"])
                )
            )
            assert wait is not None
            return wait

    wait = asyncio.run(read_wait())
    assert wait.status.value == "cancelled"
    assert wait.outcome == "run_cancelled"


def test_agent_runtime_claims_executes_and_checkpoints_graph(client: TestClient) -> None:
    incident = _investigating_incident(client)
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={"idempotencyKey": "agent-runtime-complete-001", "maxIterations": 3},
    ).json()
    handler = _FinishingNodeHandler()
    worker = AgentRuntimeWorker(
        client.app.state.database,
        handler,
        owner="runtime-test-worker",
    )

    assert asyncio.run(worker.run_once()) is True
    completed = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert completed["status"] == "completed"
    assert completed["runtimeAttempt"] == 1
    checkpoints = client.get(f"/api/v1/investigation-runs/{run['id']}/checkpoints").json()
    assert len(checkpoints) == 11
    assert checkpoints[-1]["node"] == "escalate_or_finish"
    assert checkpoints[-1]["nextAction"] == "finish"
    assert handler.executed == [
        "load_incident:0",
        "load_topology:0",
        "load_recent_changes:0",
        "classify_complexity:0",
        "create_plan:0",
        "select_next_step:0",
        "run_investigator:0",
        "assess_evidence:0",
        "propose_action:0",
        "maybe_replan:0",
        "escalate_or_finish:0",
    ]
    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert "event: investigation.status_changed" in stream.text


def test_agent_runtime_pauses_after_no_progress_limit(client: TestClient) -> None:
    incident = _investigating_incident(client)
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={"idempotencyKey": "agent-runtime-no-progress-001", "maxIterations": 5},
    ).json()
    worker = AgentRuntimeWorker(
        client.app.state.database,
        _NoProgressNodeHandler(),
        owner="runtime-no-progress-worker",
        no_progress_limit=2,
    )

    assert asyncio.run(worker.run_once()) is True
    paused = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert paused["status"] == "paused"
    assert paused["iterationCount"] == 1
    checkpoints = client.get(f"/api/v1/investigation-runs/{run['id']}/checkpoints").json()
    assert len(checkpoints) == 15
    assert checkpoints[-1]["node"] == "maybe_replan"
    assert checkpoints[-1]["noProgressCount"] == 2
    assert checkpoints[-1]["nextAction"] == "no_progress"


def test_agent_runtime_recovers_expired_run_without_replaying_checkpoint(
    client: TestClient,
) -> None:
    incident = _investigating_incident(client)
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={"idempotencyKey": "agent-runtime-recovery-001", "maxIterations": 3},
    ).json()

    async def leave_expired_checkpoint() -> None:
        database = client.app.state.database
        async with database.session_factory() as session:
            service = InvestigationService(session)
            claimed = await service.claim_next_runtime_run(
                owner="expired-runtime-worker",
                lease_seconds=10,
            )
            assert claimed is not None
            await service.write_checkpoint(
                run_id=claimed.id,
                node_execution_id=f"{claimed.id}:load_incident:0",
                expected_run_version=claimed.version,
                node="load_incident",
                iteration=0,
                plan_step_id=None,
                hypothesis_ids=[],
                evidence_ids=[],
                completed_node_keys=["load_incident:0"],
                no_progress_count=0,
                progressed=True,
                next_action=None,
                model_requests=0,
                model_input_tokens=0,
                model_output_tokens=0,
                output_summary="Incident context was persisted before the crash",
            )
        async with database.session_factory() as session:
            record = await InvestigationRepository(session).get_run(
                claimed.id,
                for_update=True,
            )
            assert record is not None
            record.runtime_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(leave_expired_checkpoint())
    handler = _FinishingNodeHandler()
    worker = AgentRuntimeWorker(
        client.app.state.database,
        handler,
        owner="replacement-runtime-worker",
    )
    assert asyncio.run(worker.run_once()) is True

    recovered = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert recovered["status"] == "completed"
    assert recovered["runtimeAttempt"] == 2
    assert "load_incident:0" not in handler.executed
    checkpoints = client.get(f"/api/v1/investigation-runs/{run['id']}/checkpoints").json()
    assert len(checkpoints) == 11
    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": "false"},
    )
    assert "event: investigation.runtime_recovered" in stream.text


def test_agent_runtime_pauses_at_max_iterations(client: TestClient) -> None:
    incident = _investigating_incident(client)
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={"idempotencyKey": "agent-runtime-max-iterations-001", "maxIterations": 1},
    ).json()
    worker = AgentRuntimeWorker(
        client.app.state.database,
        _ContinuingNodeHandler(),
        owner="runtime-max-iterations-worker",
    )

    assert asyncio.run(worker.run_once()) is True
    paused = client.get(f"/api/v1/investigation-runs/{run['id']}").json()
    assert paused["status"] == "paused"
    checkpoints = client.get(f"/api/v1/investigation-runs/{run['id']}/checkpoints").json()
    assert len(checkpoints) == 10
    assert checkpoints[-1]["node"] == "maybe_replan"
    assert checkpoints[-1]["nextAction"] == "max_iterations"


def test_checkpoint_rejects_exhausted_model_request_budget(client: TestClient) -> None:
    incident = _investigating_incident(client)
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={
            "idempotencyKey": "agent-model-budget-001",
            "maxIterations": 2,
            "maxModelRequests": 1,
        },
    ).json()
    running = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/transitions",
        json={"target": "running", "expectedVersion": run["version"]},
    ).json()

    exhausted = client.post(
        f"/internal/v1/investigation-runs/{run['id']}/checkpoints",
        json={
            "nodeExecutionId": "node-execution-model-budget-001",
            "expectedRunVersion": running["version"],
            "node": "classify_complexity",
            "iteration": 0,
            "completedNodeKeys": ["classify_complexity:0"],
            "modelRequests": 2,
        },
    )
    assert exhausted.status_code == 409
    assert exhausted.json()["error"]["code"] == "MODEL_REQUEST_BUDGET_EXHAUSTED"


def test_provider_handler_writes_plan_and_hypothesis_references(client: TestClient) -> None:
    incident = _investigating_incident(client)
    run = client.post(
        f"/api/v1/incidents/{incident['id']}/investigation-runs",
        json={"idempotencyKey": "provider-domain-writeback-001"},
    ).json()
    handler = ProviderBackedAgentNodeHandler(
        client.app.state.database,
        _StructuredProviderStub(incident["resourceId"]),  # type: ignore[arg-type]
    )

    plan_outcome = asyncio.run(
        handler.execute(
            AgentNodeContext(
                run_id=UUID(run["id"]),
                node="create_plan",
                node_execution_id="provider-create-plan-001",
                iteration=0,
                requested_action=None,
            )
        )
    )
    assert plan_outcome.model_requests == 1
    plan = client.get(f"/api/v1/incidents/{incident['id']}/plans/current").json()
    assert plan["objective"] == "Verify service health"

    assessment = asyncio.run(
        handler.execute(
            AgentNodeContext(
                run_id=UUID(run["id"]),
                node="assess_evidence",
                node_execution_id="provider-assess-evidence-001",
                iteration=0,
                requested_action=None,
            )
        )
    )
    assert len(assessment.hypothesis_ids) == 1
    hypotheses = client.get(f"/api/v1/incidents/{incident['id']}/hypotheses").json()
    assert hypotheses[0]["summary"] == "Service health is degraded"
