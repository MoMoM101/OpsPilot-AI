# OpsPilot Backend

Runner 的部署、安全白名单和凭据生命周期见
[Runner 部署与安全配置](../docs/Runner部署与安全配置.md)。
统一 Compose、Migration Job、Secret 和非 Root 镜像说明见
[容器化部署](../docs/容器化部署.md)。

FastAPI control plane for OpsPilot. The current foundation includes application
configuration, request correlation, normalized errors, health/readiness endpoints,
versioned API routing, and framework-independent domain state machines.

## Run locally

```powershell
cd backend
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

API documentation is available at `http://localhost:8000/docs`.
Production configuration disables API documentation and requires HTTPS by default;
the health and readiness probes remain available to internal orchestrators.

## Database

Start PostgreSQL from the repository root, then apply migrations:

```powershell
docker compose up -d postgres
cd backend
alembic upgrade head
```

Migrations create environments, resources, resource relations, incidents,
incident events, evidence, investigation plans, plan steps, normalized alerts,
transactional outbox events, runner instances, runner leases, runner tasks, and
Incident observability ownership, InvestigationRun records, and Agent checkpoints. Database
availability is reported by `/api/v1/ready`; liveness remains available through
`/api/v1/health`. Readiness also checks every enabled in-process background worker.
Authenticated operators can inspect heartbeat and error details at the operational
`/api/v1/worker-health` endpoint, which is intentionally excluded from the user OpenAPI.

Initial control-plane endpoints:

```text
GET      /api/v1/setup/status
GET      /api/v1/system/preflight
POST     /api/v1/system/model-connection-check
GET      /api/v1/demo/status
POST     /api/v1/demo/initialize
POST     /api/v1/demo/cleanup
GET      /api/v1/auth/me
POST     /api/v1/principals
GET      /api/v1/principals?limit=100&offset=0
DELETE   /api/v1/principals/{principal_id}
GET      /api/v1/audit-logs
POST/GET /api/v1/environments
POST/GET /api/v1/resources
POST     /api/v1/incidents
GET      /api/v1/incidents?environmentId={id}&q={keyword}&status={status}&severity={severity}
GET      /api/v1/incidents/{id}
POST     /api/v1/incidents/{id}/transitions
POST/GET /api/v1/incidents/{id}/hypotheses
PATCH    /api/v1/incidents/{id}/hypotheses/{hypothesis_id}
GET       /api/v1/investigation-graphs
GET       /api/v1/investigation-graphs/{graph_version}
POST/GET /api/v1/incidents/{id}/investigation-runs
GET       /api/v1/investigation-runs/{run_id}
POST      /api/v1/investigation-runs/{run_id}/cancel
GET       /api/v1/investigation-runs/{run_id}/checkpoints
POST     /api/v1/incidents/{id}/plans
GET      /api/v1/incidents/{id}/plans/current
POST     /api/v1/incidents/{id}/steps/{step_id}/transitions
GET      /api/v1/incidents/{id}/stream
GET      /api/v1/incidents/{id}/evidence
GET      /api/v1/evidence/{evidence_id}
GET      /api/v1/dashboard
POST     /api/v1/alerts/webhook/alertmanager
POST     /api/v1/policies
GET      /api/v1/policies?environmentId={id}&limit=100&offset=0
PUT      /api/v1/policies/{policyId}
POST     /api/v1/policies/dry-run
POST     /api/v1/policies/evaluate
POST     /api/v1/approvals
GET      /api/v1/approvals?incidentId={id}&status={status}
POST     /api/v1/approvals/{approvalId}/decision
POST     /api/v1/actions
GET      /api/v1/actions?incidentId={id}&status={status}
POST     /api/v1/actions/{actionId}/cancel
GET      /api/v1/resource-locks
POST     /api/v1/actions/{actionId}/dispatch
GET      /api/v1/actions/{actionId}/execution
POST     /api/v1/actions/{actionId}/reconcile
GET      /api/v1/alerts
GET      /api/v1/runners
POST/GET /api/v1/runner-tasks

Runner service plane (Runner token/bootstrap authentication, excluded from user OpenAPI):

POST     /runner/v1/runners/register
POST     /runner/v1/runners/{runner_id}/heartbeat
POST     /runner/v1/runners/{runner_id}/tasks/claim
POST     /runner/v1/runners/{runner_id}/tasks/{task_id}/renew
POST     /runner/v1/runners/{runner_id}/tasks/{task_id}/complete

Internal Runtime plane (service Principal with runtime role, excluded from user OpenAPI):

POST     /internal/v1/actions/{action_id}/lock
POST     /internal/v1/actions/{action_id}/lock/renew
POST     /internal/v1/actions/{action_id}/lock/release
POST     /internal/v1/investigation-runs/{run_id}/transitions
POST     /internal/v1/investigation-runs/{run_id}/checkpoints
```

`GET /api/v1/setup/status` is a public, secret-free first-run probe. It only reports
whether authentication is enabled, whether the initial Admin exists, and whether the
configured Bootstrap credential can still be used. `GET /api/v1/system/preflight` is
Admin-only and separates blocking setup checks from operational recommendations such as
an online Runner, Agent runtime, and Alertmanager authentication.

`POST /api/v1/system/model-connection-check` is Admin-only and has no request body. It
uses only the server-side Agent Provider configuration, performs one minimal structured
request under an independent timeout, and returns fixed diagnostic codes without exposing
provider errors, credentials, model names, or base URLs. Concurrent calls are serialized;
the latest result is reused during a configurable cooldown.

The Admin-only Demo API is disabled by default and always unavailable in production.
When `OPSPILOT_DEMO_DATA_ENABLED=true` in a development, test, or staging process,
`POST /api/v1/demo/initialize` creates a versioned guided-tour workspace idempotently.
Cleanup requires the current generation and deletes only Incident IDs recorded in the
server-owned manifest; the managed Environment and Resource skeleton remains reusable,
and user-created Incidents in that workspace are never selected by name for deletion.

The Incident stream uses Server-Sent Events. Event sequence numbers are emitted
as SSE `id` values. Incident detail responses include `eventCursor`; clients
should apply that complete snapshot and reconnect with the cursor in the
`Last-Event-ID` header to resume without missing state after retention cleanup.
Incident detail embeds at most the 100 newest durable timeline events and exposes
`timelineTotal`/`timelineTruncated`; older events are available from the bounded
`GET /api/v1/incidents/{incidentId}/timeline` endpoint.

Incident hypotheses are structured, versioned records with a confidence score,
status, and explicit supporting/contradicting Evidence IDs. Updates use
`expectedVersion` optimistic concurrency. Incident and Dashboard responses embed
the highest-confidence non-rejected hypothesis as `hypothesis`; the full history
is available from the Incident-scoped endpoint. Changes emit
`hypothesis.created` and `hypothesis.updated` SSE events.

Plan dependencies reference preceding one-based step ordinals. Plan creation
rejects forward, self, malformed, and duplicate dependencies. A step cannot enter
`running` until every dependency is `completed` or `skipped`. Evidence IDs added
to a step are checked against the same Incident before the transition is stored;
unknown, malformed, or cross-Incident references are rejected.

Investigation runs provide the durable execution boundary for the Agent runtime.
LangGraph schedules registered nodes while PostgreSQL remains the source of execution
truth. Each run has a stable `threadId`, graph version, iteration limit,
optimistic version, and `queued/running/paused/completed/failed/cancelled` state.
Structured checkpoints use a per-node `nodeExecutionId` for idempotency and store
only node/iteration metadata, completed-node keys, short summaries, and validated
PlanStep/Hypothesis/Evidence references. Hidden model reasoning and full message
history are intentionally not persisted. Events are emitted as
`investigation.run_created`, `investigation.status_changed`, and
`investigation.checkpointed`. A database-backed runtime lease allows another control-plane
worker to recover an expired `running` run without replaying completed node keys; recovery
emits `investigation.runtime_recovered`.

The `run_investigator` node can select one parameter-free Observation Proposal.
The server compiles its RunnerTask exclusively from the Resource's trusted
`observability.runnerOperations` configuration. The checkpoint, persistent
Observation wait, queued RunnerTask, and run pause commit atomically. Successful
and failed task completions both create bounded Evidence and requeue the paused
run without replaying the completed Agent node. Cancelling the run also cancels
its active Observation wait and RunnerTask.

The runtime is disabled by default. Enabling it requires an OpenAI-compatible model name and
API key; an optional base URL supports local Ollama/vLLM and compatible providers. PydanticAI
validates typed Planner, Investigator, and Replanner output. Only bounded Incident fields and
Evidence references/summaries are sent to the provider. Model requests and input/output tokens
are persisted per checkpoint and accumulated on the Run; `maxModelRequests` is enforced
transactionally. Configure runtime behavior with `OPSPILOT_AGENT_RUNTIME_*` and model limits
with `OPSPILOT_AGENT_MODEL_*` settings.
Model diagnostic execution is bounded by
`OPSPILOT_AGENT_MODEL_CHECK_TIMEOUT_SECONDS` (default 15 seconds) and
`OPSPILOT_AGENT_MODEL_CHECK_COOLDOWN_SECONDS` (default 30 seconds).

Alertmanager requests are normalized and deduplicated by fingerprint and start
time. Set `OPSPILOT_ALERTMANAGER_WEBHOOK_TOKEN` and send the same value in the
`X-OpsPilot-Webhook-Token` header. The token is mandatory when the application
environment is `production`.

Runner registration returns a one-time access token; only its SHA-256 digest is
stored. Heartbeats authenticate with `Authorization: Bearer <token>`, renew the
runner lease, and return a monotonically increasing fencing token. Reusing a
heartbeat ID is idempotent and does not increment that token. Connector
capabilities are declarative and reject arbitrary shell/command execution.

Runner tokens rotate automatically through heartbeat responses. The Runner
persists a returned token atomically before using it, while the previous token
has a short recovery grace period for lost responses. Configure rotation,
hard expiry, and grace with `OPSPILOT_RUNNER_TOKEN_ROTATION_SECONDS`,
`OPSPILOT_RUNNER_TOKEN_TTL_SECONDS`, and `OPSPILOT_RUNNER_TOKEN_GRACE_SECONDS`.

Set `OPSPILOT_RUNNER_BOOTSTRAP_TOKEN` and send it in the
`X-OpsPilot-Runner-Bootstrap-Token` header when registering a runner. The token
is mandatory in `production`. Lease duration is configured with
`OPSPILOT_RUNNER_LEASE_SECONDS`.

Runner tasks accept the Docker read-only operations `docker.list_containers`,
`docker.inspect_container`, `docker.container_logs`, and
`docker.container_health`, plus the bounded log operations `file.tail` and
`journal.query`, and the allowlisted health operations `http.probe` and
`tcp.probe`, plus `prometheus.query`, `prometheus.query_range`, and the
parameter-free `host.snapshot`. SQLite `health/lock_status/integrity_check`, Qdrant
`health/collection/point_count/query_smoke`, and `rag.business_health` are also
available through strict task schemas and Runner-local target allowlists.
Claiming is capability- and environment-aware
and uses row locking, leases, and fencing tokens. Completion is idempotent,
creates normalized Evidence for observations, truncates oversized
output, and applies server-side secret redaction as a second line of defense.
Configure task leases and output limits with `OPSPILOT_RUNNER_TASK_LEASE_SECONDS` and
`OPSPILOT_RUNNER_TASK_MAX_OUTPUT_BYTES`.

Runner tasks created while an Incident has an active plan must include
`planStepId`. The step must be running, observational, allowlist the requested
operation, and include the Resource in its scope when a scope is declared. Each
new idempotent task consumes one Incident tool-budget unit; replaying the same
idempotency key does not consume another unit. Successful task Evidence is
automatically attached to the originating PlanStep. Task responses expose the
optional `planStepId`, and list requests can filter by `plan_step_id`.

Creating a replacement plan cancels queued or leased Runner tasks owned by the
superseded plan. Moving a step to `completed`, `failed`, `blocked`, or `skipped`
also cancels any remaining active tasks for that step. Cancellation clears task
leases and fencing tokens, preserves consumed tool budget, and emits
`runner_task.cancelled` with a deterministic reason such as `PLAN_SUPERSEDED` or
`PLAN_STEP_FAILED`.

The control plane scans expired Runner leases every 15 seconds by default. Set
`OPSPILOT_OBSERVABILITY_MONITOR_INTERVAL_SECONDS` to tune that interval. An
expired Runner is marked offline, its leased tasks are requeued or failed, and
only Investigating Incidents that own those tasks enter `OBSERVABILITY_LOST`.
The same Runner's next heartbeat restores those Incidents to `INVESTIGATING`.
Incident responses expose `observabilityStatus`, `observabilityRunnerId`, and
`observabilityLostAt`; SSE emits `incident.observability_lost` and
`incident.observability_restored`.

Before accepting control-plane writes, startup recovery expires stale Runners
and changes expired Action and Compensation executions to `unknown`. If any
recovery step fails, `/api/v1/ready` returns 503 and the process remains
read-only while retrying every 30 seconds. Read APIs and authentication remain
available; new Runner Action claims pause, while renew/complete calls for work
already in flight stay available. Operators can inspect `GET /api/v1/system/mode`,
and an Admin can trigger an immediate retry with `POST /api/v1/system/recovery`.
Configure this with `OPSPILOT_STARTUP_RECOVERY_ENABLED` and
`OPSPILOT_STARTUP_RECOVERY_RETRY_SECONDS`.

The monitor and optional Agent Runtime publish in-memory heartbeats, last-success
timestamps, consecutive/total error counts, and task liveness. Three consecutive
errors or a stale/terminated worker makes `/api/v1/ready` return 503. Tune these
thresholds with `OPSPILOT_WORKER_HEALTH_STALE_MULTIPLIER` and
`OPSPILOT_WORKER_HEALTH_ERROR_THRESHOLD`.

Successful read-only Runner tasks create immutable Evidence records. Evidence
responses include the Incident and Resource IDs, source, content hash, redaction
flag, observation window, collection timestamp/status, time confidence, and the
bounded normalized payload. Use the Incident-scoped endpoint for pagination and
filtering by `evidence_type` or `resource_id`; use the Evidence detail endpoint
when resolving an `evidenceId` from RunnerTask or SSE data.

## Verify

```powershell
pytest
ruff check .
mypy app
python -m app.evaluation
```

The offline Agent Eval gate loads the versioned JSONL dataset bundled under
`app/evaluation/data`, executes the deterministic Lab Provider without network
or model credentials, prints a machine-readable report, and exits non-zero when
operation accuracy, resource scoping, Evidence grounding, decision accuracy,
schema validity, overall pass rate, or unsafe Action rate crosses its threshold.
Use `python -m app.evaluation --output eval-report.json` to retain the report.

Operator-run maintenance commands are intentionally separate from the Web
process. Use `python -m app.operations.database_backup create|verify|restore`
for PostgreSQL custom-format backups and protected empty-database restores. Use
`python -m app.operations.audit_archive --directory <durable-path>` to archive
expired Control Plane audit rows only after a checksummed gzip JSONL export is
durable. See `docs/备份恢复与审计归档.md` before scheduling either command.
