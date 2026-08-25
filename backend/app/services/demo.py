from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.domain.incidents import IncidentStatus, Severity, transition_incident
from app.schemas.demo import (
    DemoCleanupResponse,
    DemoInitializeResponse,
    DemoStatusResponse,
)
from app.services.events import EventRecorder
from app.storage.models import (
    DemoInstallationRecord,
    EnvironmentRecord,
    IncidentRecord,
    ResourceRecord,
    ResourceRelationRecord,
)
from app.storage.repositories import (
    EnvironmentRepository,
    EvidenceRepository,
    HypothesisRepository,
    IncidentRepository,
    ResourceRepository,
)
from app.storage.transactions import commit_session

_DEMO_KEY = "guided_tour"
_MANIFEST_VERSION = 1
_ENVIRONMENT_NAME = "OpsPilot Guided Demo"
_ENVIRONMENT_SLUG = "opspilot-guided-demo"
_MANAGED_MARKER = "managed-by:opspilot-demo:v1"


class DemoDataService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.environments = EnvironmentRepository(session)
        self.resources = ResourceRepository(session)
        self.incidents = IncidentRepository(session)
        self.evidence = EvidenceRepository(session)
        self.hypotheses = HypothesisRepository(session)
        self.events = EventRecorder(session)

    async def status(self) -> DemoStatusResponse:
        availability = self._availability()
        installation = await self._installation()
        if not availability[0]:
            return self._response(
                installation,
                status="unavailable",
                available=False,
                reason_code=availability[1],
            )
        status = "inactive"
        if installation is not None and installation.active:
            status = "active" if await self._owned_incidents_intact(installation) else "drifted"
        return self._response(
            installation,
            status=status,
            available=True,
            reason_code=None,
        )

    async def initialize(self) -> DemoInitializeResponse:
        self._require_available()
        installation = await self._installation(for_update=True)
        if installation is None:
            installation = DemoInstallationRecord(
                key=_DEMO_KEY,
                manifest_version=_MANIFEST_VERSION,
                generation=0,
                resource_ids=[],
                incident_ids=[],
                active=False,
            )
            self.session.add(installation)
            await self.session.flush()
        if installation.active:
            if not await self._owned_incidents_intact(installation):
                raise ApplicationError(
                    "DEMO_DATA_DRIFT",
                    "Managed Demo Incident ownership has drifted; cleanup requires operator review",
                    409,
                )
            return DemoInitializeResponse(
                **self._response(
                    installation,
                    status="active",
                    available=True,
                    reason_code=None,
                ).model_dump(),
                replayed=True,
            )

        resource_records = await self._ensure_workspace(installation)
        incident_ids = [
            await self._create_story(
                resource_records[0],
                title="Checkout latency after payment dependency degradation",
                severity=Severity.HIGH,
                transitions=[
                    IncidentStatus.CORRELATING,
                    IncidentStatus.INVESTIGATING,
                ],
                evidence_summary="Checkout p95 latency rose above the demo baseline",
                hypothesis_summary="Payment dependency latency is propagating to checkout",
            ),
            await self._create_story(
                resource_records[2],
                title="Payment gateway timeout recovered after bounded mitigation",
                severity=Severity.CRITICAL,
                transitions=[
                    IncidentStatus.CORRELATING,
                    IncidentStatus.INVESTIGATING,
                    IncidentStatus.DIAGNOSED,
                    IncidentStatus.PLANNING,
                    IncidentStatus.WAITING_APPROVAL,
                    IncidentStatus.REMEDIATING,
                    IncidentStatus.VERIFYING,
                    IncidentStatus.RESOLVED,
                    IncidentStatus.CLOSED,
                ],
                evidence_summary="Payment timeout rate returned to the demo recovery threshold",
                hypothesis_summary="A bounded upstream timeout caused payment request saturation",
            ),
        ]
        installation.manifest_version = _MANIFEST_VERSION
        installation.generation += 1
        installation.incident_ids = [str(item) for item in incident_ids]
        installation.active = True
        installation.updated_at = datetime.now(UTC)
        await commit_session(self.session)
        return DemoInitializeResponse(
            **self._response(
                installation,
                status="active",
                available=True,
                reason_code=None,
            ).model_dump(),
            replayed=False,
        )

    async def cleanup(self, expected_generation: int) -> DemoCleanupResponse:
        self._require_available()
        installation = await self._installation(for_update=True)
        if installation is None or not installation.active:
            response = self._response(
                installation,
                status="inactive",
                available=True,
                reason_code=None,
            )
            return DemoCleanupResponse(
                **response.model_dump(),
                replayed=True,
                deleted_incident_count=0,
            )
        if installation.generation != expected_generation:
            raise ApplicationError(
                "DEMO_GENERATION_CONFLICT",
                "Demo generation has changed; reload status before cleanup",
                409,
            )
        owned_ids = [UUID(item) for item in installation.incident_ids]
        manifest_ids = set(owned_ids)
        records = list(
            await self.session.scalars(
                select(IncidentRecord).where(IncidentRecord.id.in_(owned_ids)).with_for_update()
            )
        )
        database_ids = {record.id for record in records}
        if len(manifest_ids) != len(owned_ids) or database_ids != manifest_ids:
            raise ApplicationError(
                "DEMO_DATA_DRIFT",
                "Managed Demo Incident manifest does not match the database",
                409,
            )
        owned_resources = {UUID(item) for item in installation.resource_ids}
        if any(record.resource_id not in owned_resources for record in records):
            raise ApplicationError(
                "DEMO_DATA_DRIFT",
                "Managed Demo ownership no longer matches its Resource manifest",
                409,
            )
        existing_ids = [record.id for record in records]
        if existing_ids:
            await self.session.execute(
                delete(IncidentRecord).where(IncidentRecord.id.in_(existing_ids))
            )
        installation.incident_ids = []
        installation.active = False
        installation.updated_at = datetime.now(UTC)
        await commit_session(self.session)
        response = self._response(
            installation,
            status="inactive",
            available=True,
            reason_code=None,
        )
        return DemoCleanupResponse(
            **response.model_dump(),
            replayed=False,
            deleted_incident_count=len(existing_ids),
        )

    async def _installation(self, *, for_update: bool = False) -> DemoInstallationRecord | None:
        statement = select(DemoInstallationRecord).where(DemoInstallationRecord.key == _DEMO_KEY)
        if for_update:
            statement = statement.with_for_update()
        return cast(DemoInstallationRecord | None, await self.session.scalar(statement))

    async def _ensure_workspace(
        self, installation: DemoInstallationRecord
    ) -> list[ResourceRecord]:
        if installation.environment_id is None:
            conflict = await self.session.scalar(
                select(EnvironmentRecord).where(
                    or_(
                        EnvironmentRecord.slug == _ENVIRONMENT_SLUG,
                        EnvironmentRecord.name == _ENVIRONMENT_NAME,
                    )
                )
            )
            if conflict is not None:
                raise ApplicationError(
                    "DEMO_WORKSPACE_CONFLICT",
                    "Reserved Demo Environment name or slug is already in use",
                    409,
                )
            environment = await self.environments.create(
                _ENVIRONMENT_NAME,
                _ENVIRONMENT_SLUG,
                f"[{_MANAGED_MARKER}] Reproducible guided product tour workspace",
            )
            resources = [
                await self.resources.create(
                    environment.id,
                    name,
                    kind,
                    criticality,
                    {
                        "demoManaged": True,
                        "demoManifestVersion": _MANIFEST_VERSION,
                        "component": component,
                    },
                )
                for name, kind, criticality, component in (
                    ("checkout-api", "service", "critical", "checkout"),
                    ("orders-postgres", "database", "high", "orders"),
                    ("payment-gateway", "external_service", "critical", "payment"),
                )
            ]
            self.session.add_all(
                [
                    ResourceRelationRecord(
                        source_id=resources[0].id,
                        target_id=resources[1].id,
                        relation_type="depends_on",
                    ),
                    ResourceRelationRecord(
                        source_id=resources[0].id,
                        target_id=resources[2].id,
                        relation_type="depends_on",
                    ),
                ]
            )
            await self.session.flush()
            installation.environment_id = environment.id
            installation.resource_ids = [str(item.id) for item in resources]
            return resources

        environment_record = await self.session.get(
            EnvironmentRecord, installation.environment_id
        )
        resource_ids = [UUID(item) for item in installation.resource_ids]
        resources = list(
            await self.session.scalars(
                select(ResourceRecord).where(ResourceRecord.id.in_(resource_ids))
            )
        )
        if (
            environment_record is None
            or _MANAGED_MARKER not in (environment_record.description or "")
            or len(resources) != 3
            or any(
                item.environment_id != installation.environment_id
                or item.attributes.get("demoManaged") is not True
                or item.attributes.get("demoManifestVersion") != _MANIFEST_VERSION
                for item in resources
            )
        ):
            raise ApplicationError(
                "DEMO_DATA_DRIFT",
                "Managed Demo workspace has changed and will not be overwritten",
                409,
            )
        by_name = {item.name: item for item in resources}
        expected_names = {"checkout-api", "orders-postgres", "payment-gateway"}
        if set(by_name) != expected_names:
            raise ApplicationError(
                "DEMO_DATA_DRIFT",
                "Managed Demo Resource manifest has changed and will not be overwritten",
                409,
            )
        return [by_name["checkout-api"], by_name["orders-postgres"], by_name["payment-gateway"]]

    async def _create_story(
        self,
        resource: ResourceRecord,
        *,
        title: str,
        severity: Severity,
        transitions: list[IncidentStatus],
        evidence_summary: str,
        hypothesis_summary: str,
    ) -> UUID:
        incident = await self.incidents.create(title, severity, resource.id, "demo-operator")
        now = datetime.now(UTC)
        await self.events.record(
            incident,
            "incident.created",
            now,
            "system",
            {"status": incident.status.value, "demoGeneration": True},
        )
        evidence_id: UUID | None = None
        for target in transitions:
            previous = incident.status
            incident.status = transition_incident(previous, target)
            incident.version += 1
            incident.updated_at = datetime.now(UTC)
            await self.events.record(
                incident,
                "incident.status_changed",
                incident.updated_at,
                "system",
                {"from": previous.value, "to": target.value, "version": incident.version},
            )
            if target == IncidentStatus.INVESTIGATING:
                evidence = await self.evidence.create(
                    incident_id=incident.id,
                    resource_id=resource.id,
                    evidence_type="metric",
                    source="demo.synthetic",
                    summary=evidence_summary,
                    content_hash=sha256(evidence_summary.encode()).hexdigest(),
                    redacted=False,
                    observed_from=now,
                    observed_to=incident.updated_at,
                    collected_at=incident.updated_at,
                    collection_status="succeeded",
                    time_confidence="control_plane",
                    data={"demo": True, "signal": "bounded synthetic evidence"},
                )
                evidence_id = evidence.id
                hypothesis = await self.hypotheses.create(
                    incident_id=incident.id,
                    summary=hypothesis_summary,
                    confidence=92,
                    supporting_evidence_ids=[str(evidence.id)],
                    contradicting_evidence_ids=[],
                )
                await self.events.record(
                    incident,
                    "hypothesis.created",
                    incident.updated_at,
                    "agent",
                    {"hypothesisId": str(hypothesis.id), "confidence": 92},
                    aggregate_type="hypothesis",
                    aggregate_id=hypothesis.id,
                    aggregate_version=hypothesis.version,
                )
        if evidence_id is not None:
            await self.events.record(
                incident,
                "evidence.collected",
                datetime.now(UTC),
                "runner",
                {"evidenceId": str(evidence_id), "source": "demo.synthetic"},
            )
        return incident.id

    async def _owned_incidents_intact(self, installation: DemoInstallationRecord) -> bool:
        incident_ids = [UUID(item) for item in installation.incident_ids]
        if not incident_ids:
            return False
        records = (
            await self.session.execute(
                select(IncidentRecord.id, IncidentRecord.resource_id).where(
                    IncidentRecord.id.in_(incident_ids)
                )
            )
        ).tuples().all()
        owned_resources = {UUID(item) for item in installation.resource_ids}
        return len(records) == len(incident_ids) and all(
            resource_id in owned_resources for _, resource_id in records
        )

    def _availability(self) -> tuple[bool, str | None]:
        if self.settings.environment == "production":
            return False, "PRODUCTION_DISABLED"
        if not self.settings.demo_data_enabled:
            return False, "DEMO_DISABLED"
        return True, None

    def _require_available(self) -> None:
        available, reason = self._availability()
        if not available:
            raise ApplicationError(reason or "DEMO_DISABLED", "Demo data is not available", 404)

    @staticmethod
    def _response(
        installation: DemoInstallationRecord | None,
        *,
        status: str,
        available: bool,
        reason_code: str | None,
    ) -> DemoStatusResponse:
        return DemoStatusResponse(
            available=available,
            reason_code=reason_code,
            status=status,
            manifest_version=(
                installation.manifest_version if installation is not None else _MANIFEST_VERSION
            ),
            generation=installation.generation if installation is not None else 0,
            environment_id=installation.environment_id if installation is not None else None,
            resource_ids=(
                [UUID(item) for item in installation.resource_ids]
                if installation is not None
                else []
            ),
            incident_ids=(
                [UUID(item) for item in installation.incident_ids]
                if installation is not None
                else []
            ),
        )
