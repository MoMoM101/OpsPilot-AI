from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.domain.runner_tasks import RunnerReadOperation
from app.domain.runners import RunnerStatus
from app.schemas.connectors import (
    ConnectorAvailabilityResponse,
    ConnectorCatalogItemResponse,
    ConnectorCatalogResponse,
)
from app.services.observability import ObservabilityService
from app.storage.models import RunnerRecord
from app.storage.repositories import EnvironmentRepository, RunnerRepository


@dataclass(frozen=True, slots=True)
class ConnectorDefinition:
    connector: str
    setup_kind: str
    runner_setting_keys: tuple[str, ...]
    prerequisites: tuple[str, ...]
    supported_platforms: tuple[str, ...]
    observe_operations: tuple[str, ...]
    action_operations: tuple[str, ...] = ()
    contract_version: str = "1.0"


CONNECTOR_DEFINITIONS = (
    ConnectorDefinition(
        "docker",
        "built_in",
        (),
        ("docker_cli_access",),
        ("linux", "windows", "macos"),
        (
            "docker.list_containers",
            "docker.inspect_container",
            "docker.container_logs",
            "docker.container_health",
        ),
        ("container.restart", "health.check"),
    ),
    ConnectorDefinition(
        "host",
        "built_in",
        (),
        (),
        ("linux", "windows", "macos"),
        ("host.snapshot",),
    ),
    ConnectorDefinition(
        "file",
        "allowlist",
        ("OPSPILOT_RUNNER_LOG_ALLOWED_ROOTS",),
        ("readable_allowed_roots",),
        ("linux", "windows", "macos"),
        ("file.tail",),
    ),
    ConnectorDefinition(
        "journal",
        "allowlist",
        ("OPSPILOT_RUNNER_JOURNAL_ALLOWED_UNITS",),
        ("journalctl",),
        ("linux",),
        ("journal.query",),
    ),
    ConnectorDefinition(
        "http",
        "allowlist",
        ("OPSPILOT_RUNNER_PROBE_ALLOWED_HOSTS", "OPSPILOT_RUNNER_PROBE_ALLOWED_PORTS"),
        ("network_reachability",),
        ("linux", "windows", "macos"),
        ("http.probe",),
    ),
    ConnectorDefinition(
        "tcp",
        "allowlist",
        ("OPSPILOT_RUNNER_PROBE_ALLOWED_HOSTS", "OPSPILOT_RUNNER_PROBE_ALLOWED_PORTS"),
        ("network_reachability",),
        ("linux", "windows", "macos"),
        ("tcp.probe",),
    ),
    ConnectorDefinition(
        "prometheus",
        "allowlist",
        ("OPSPILOT_RUNNER_PROBE_ALLOWED_HOSTS", "OPSPILOT_RUNNER_PROBE_ALLOWED_PORTS"),
        ("network_reachability",),
        ("linux", "windows", "macos"),
        ("prometheus.query", "prometheus.query_range"),
    ),
    ConnectorDefinition(
        "sqlite",
        "allowlist",
        ("OPSPILOT_RUNNER_SQLITE_ALLOWED_ROOTS",),
        ("readable_allowed_roots",),
        ("linux", "windows", "macos"),
        ("sqlite.health", "sqlite.lock_status", "sqlite.integrity_check"),
    ),
    ConnectorDefinition(
        "qdrant",
        "allowlist",
        ("OPSPILOT_RUNNER_PROBE_ALLOWED_HOSTS", "OPSPILOT_RUNNER_PROBE_ALLOWED_PORTS"),
        ("network_reachability",),
        ("linux", "windows", "macos"),
        (
            "qdrant.health",
            "qdrant.collection",
            "qdrant.point_count",
            "qdrant.query_smoke",
        ),
    ),
    ConnectorDefinition(
        "rag",
        "allowlist",
        ("OPSPILOT_RUNNER_PROBE_ALLOWED_HOSTS", "OPSPILOT_RUNNER_PROBE_ALLOWED_PORTS"),
        ("network_reachability",),
        ("linux", "windows", "macos"),
        ("rag.business_health",),
    ),
)


class ConnectorCatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.runners = RunnerRepository(session)
        self.environments = EnvironmentRepository(session)

    async def get_catalog(self, environment_id: UUID | None) -> ConnectorCatalogResponse:
        if environment_id is not None and await self.environments.get(environment_id) is None:
            raise ApplicationError("ENVIRONMENT_NOT_FOUND", "Environment does not exist", 404)
        now = datetime.now(UTC)
        await ObservabilityService(self.session).expire_stale_runners(now)
        runners = await self.runners.list_for_connector_catalog(environment_id)
        return ConnectorCatalogResponse(
            environment_id=environment_id,
            connectors=[
                self._item(definition, runners, now) for definition in CONNECTOR_DEFINITIONS
            ],
        )

    @staticmethod
    def _item(
        definition: ConnectorDefinition,
        runners: list[RunnerRecord],
        now: datetime,
    ) -> ConnectorCatalogItemResponse:
        configured = []
        compatible = []
        incompatible = []
        online = []
        for runner in runners:
            capability = ConnectorCatalogService._capability(runner, definition.connector)
            if capability is None:
                continue
            configured.append(runner)
            contract_version = capability.get("contractVersion")
            if not ConnectorCatalogService._compatible_contract(
                contract_version, definition.contract_version
            ):
                incompatible.append(runner)
                continue
            compatible.append(runner)
            if (
                runner.status == RunnerStatus.ONLINE
                and ConnectorCatalogService._as_utc(runner.lease_expires_at) > now
            ):
                online.append(runner)

        observe = ConnectorCatalogService._operation_union(
            online, definition.connector, "observe"
        )
        actions = ConnectorCatalogService._operation_union(
            online, definition.connector, "actions"
        )
        status = ConnectorCatalogService._status(
            definition,
            configured_count=len(configured),
            compatible_count=len(compatible),
            online_count=len(online),
            incompatible_count=len(incompatible),
            observe=observe,
            actions=actions,
        )
        return ConnectorCatalogItemResponse(
            connector=definition.connector,
            contract_version=definition.contract_version,
            setup_kind=definition.setup_kind,
            runner_setting_keys=list(definition.runner_setting_keys),
            prerequisites=list(definition.prerequisites),
            supported_platforms=list(definition.supported_platforms),
            observe_operations=list(definition.observe_operations),
            action_operations=list(definition.action_operations),
            availability=ConnectorAvailabilityResponse(
                status=status,
                configured_runner_count=len(configured),
                compatible_runner_count=len(compatible),
                online_runner_count=len(online),
                incompatible_runner_count=len(incompatible),
                ready_observe_operations=sorted(observe),
                ready_action_operations=sorted(actions),
            ),
        )

    @staticmethod
    def _status(
        definition: ConnectorDefinition,
        *,
        configured_count: int,
        compatible_count: int,
        online_count: int,
        incompatible_count: int,
        observe: set[str],
        actions: set[str],
    ) -> str:
        if configured_count == 0:
            return "not_configured"
        if compatible_count == 0 and incompatible_count:
            return "incompatible"
        if online_count == 0:
            return "offline"
        if set(definition.observe_operations) <= observe and set(
            definition.action_operations
        ) <= actions:
            return "ready"
        return "partial"

    @staticmethod
    def _capability(runner: RunnerRecord, connector: str) -> dict[str, object] | None:
        capabilities = runner.capabilities.get("connectors", [])
        if not isinstance(capabilities, list):
            return None
        for capability in capabilities:
            if isinstance(capability, dict) and capability.get("connector") == connector:
                return capability
        return None

    @staticmethod
    def _operation_union(
        runners: list[RunnerRecord], connector: str, key: str
    ) -> set[str]:
        result: set[str] = set()
        for runner in runners:
            capability = ConnectorCatalogService._capability(runner, connector)
            operations = capability.get(key, []) if capability is not None else []
            if isinstance(operations, list):
                result.update(item for item in operations if isinstance(item, str))
        return result

    @staticmethod
    def _compatible_contract(value: object, expected: str) -> bool:
        if not isinstance(value, str):
            return False
        return value.partition(".")[0] == expected.partition(".")[0]

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def catalog_observe_operations() -> frozenset[str]:
    return frozenset(
        operation
        for definition in CONNECTOR_DEFINITIONS
        for operation in definition.observe_operations
    )


def runner_read_operations() -> frozenset[str]:
    return frozenset(operation.value for operation in RunnerReadOperation)
