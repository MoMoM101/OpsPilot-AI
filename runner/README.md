# OpsPilot Runner

中文部署、安全边界和故障排查说明见
[Runner 部署与安全配置](../docs/Runner部署与安全配置.md)。

The Runner is the isolated execution plane for OpsPilot. It polls the control
plane for leased observation tasks and approved, policy-checked Actions.

Supported operations:

```text
docker.list_containers
docker.inspect_container
docker.container_logs
docker.container_health
file.tail
journal.query
http.probe
tcp.probe
prometheus.query
prometheus.query_range
host.snapshot
sqlite.health
sqlite.lock_status
sqlite.integrity_check
qdrant.health
qdrant.collection
qdrant.point_count
qdrant.query_smoke
rag.business_health
```

Supported Actions are intentionally small and explicit:

```text
container.restart   # parameter: containerId
health.check        # parameter: target (Docker container ID or name)
```

The Connector invokes the Docker CLI with a fixed executable and argument list.
It never uses a shell, validates container identifiers and every parameter,
bounds log lines and execution time, filters binary decoding errors, redacts
secrets locally, and truncates observation output before upload. The Action
connector only builds fixed Docker CLI argument vectors for the two advertised
capabilities. It contains no stop, remove, exec, or arbitrary command capability.

While a Connector is running, the Runner continues control-plane heartbeats and
renews the task lease before expiry. A stale lease or fencing token cancels the
local read-only execution and suppresses result upload. Configure the maximum
renew interval with `OPSPILOT_RUNNER_TASK_RENEW_SECONDS`; the Runner shortens it
automatically when the remaining server lease is smaller.

During an Action, the Runner renews both the Action Execution lease and Resource
Lock while continuing heartbeats. Configure the maximum interval with
`OPSPILOT_RUNNER_ACTION_RENEW_SECONDS` and the local execution ceiling with
`OPSPILOT_RUNNER_ACTION_TIMEOUT_SECONDS`. A stale fencing token cancels the local
process and suppresses completion. Completion retries reuse one `completionId`;
an expired execution becomes `unknown` in the control plane and must be reconciled
before another write is attempted.

Production Runner configuration requires an HTTPS control-plane URL. Heartbeat
responses may rotate the Runner access token; the new token is written to the
credential file atomically before the in-memory client switches to it. A private
single-host Compose network may explicitly opt into HTTP, but cross-host Runner
traffic must not use that exception.

File logs are disabled until `OPSPILOT_RUNNER_LOG_ALLOWED_ROOTS` is configured;
resolved paths must remain inside those roots. Journal queries are disabled until
`OPSPILOT_RUNNER_JOURNAL_ALLOWED_UNITS` is configured and accept only allowlisted
systemd units, bounded line counts, time windows, and priorities. The Runner only
advertises configured Connectors, so it cannot claim tasks it is unable to run.

HTTP and TCP probes are disabled until both
`OPSPILOT_RUNNER_PROBE_ALLOWED_HOSTS` and
`OPSPILOT_RUNNER_PROBE_ALLOWED_PORTS` are configured. HTTP probes allow only
`GET` and `HEAD`, reject credentials/query strings/fragments, ignore system proxy
settings, and never follow redirects. Response bodies are disabled by default and
bounded to a small redacted preview when explicitly requested. TCP probes only
open and close a connection; they send no application data.

Prometheus queries reuse the same host and port allowlist. Instant PromQL queries
are limited to 2000 characters. Range queries are limited to six hours and 11000
points per series; responses are capped at 1 MiB before parsing and normalized to
bounded series, label, and sample counts before Evidence upload.

SQLite diagnostics are disabled until `OPSPILOT_RUNNER_SQLITE_ALLOWED_ROOTS` is
configured. Database files are resolved inside those roots and opened with
SQLite `mode=ro` plus `query_only`; no SQL text is accepted from a task. Health,
lock/WAL status, and bounded integrity results are the only advertised operations.

Qdrant and RAG diagnostics reuse the probe host/port allowlist. Qdrant operations
accept only bounded collection names and, for smoke queries, a finite vector of
at most 4096 values. Result payloads exclude point payloads and vectors. RAG
business health sends one bounded `question` JSON field to a fixed trusted URL,
checks an `answer` field and bounded expected terms, and uploads only a redacted
2 KiB preview. Both connectors cap responses at 1 MiB and never follow redirects.

`host.snapshot` requires no additional configuration and never invokes a shell.
It reports bounded platform, CPU/load, memory, root disk, uptime, network counter,
and process-count fields. It does not collect process names, command lines,
environment variables, IP addresses, or MAC addresses. Non-Linux platforms omit
Linux `/proc` fields that are unavailable.

## Install and verify

```powershell
cd runner
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy opspilot_runner
python -m opspilot_runner docker-list
python -m opspilot_runner host-snapshot
```

## Connect to the control plane

Copy `.env.example` to `.env`, set `OPSPILOT_RUNNER_ENVIRONMENT_ID`, and then run:

```powershell
python -m opspilot_runner serve
```

On first start the Runner registers and writes its one-time access token to the
configured credential file. Keep that file private and persistent. Deleting it
does not revoke the server-side Runner identity; an administrator must rotate or
replace that identity before re-registering the same name.
