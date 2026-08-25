from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.actions import (
    ActionProposalStatus,
    ActionRequestStatus,
    ActionVerificationStatus,
    CompensationStatus,
)
from app.domain.alerts import AlertStatus
from app.domain.approvals import ApprovalStatus
from app.domain.hypotheses import HypothesisStatus
from app.domain.incidents.models import IncidentStatus, Severity
from app.domain.investigations import (
    InvestigationHITLSubjectType,
    InvestigationHITLWaitStatus,
    InvestigationObservationWaitStatus,
    InvestigationRunStatus,
)
from app.domain.plans import PlanStatus, PlanStepRisk, PlanStepStatus, PlanStepType
from app.domain.policies import PolicyEffect
from app.domain.runner_tasks import RunnerTaskStatus
from app.domain.runners import RunnerStatus
from app.domain.security import PrincipalKind, PrincipalRole
from app.storage.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EnvironmentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "environments"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)


class ApiPrincipalRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_principals"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    kind: Mapped[PrincipalKind] = mapped_column(
        Enum(
            PrincipalKind,
            name="principal_kind",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    role: Mapped[PrincipalRole] = mapped_column(
        Enum(
            PrincipalRole,
            name="principal_role",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    environment_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    unrestricted_environments: Mapped[bool] = mapped_column(default=False, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    token_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlPlaneSetupRecord(Base):
    __tablename__ = "control_plane_setup"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_principal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("api_principals.id", ondelete="SET NULL")
    )


class DemoInstallationRecord(TimestampMixin, Base):
    __tablename__ = "demo_installations"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    manifest_version: Mapped[int] = mapped_column(Integer, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    environment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), unique=True
    )
    resource_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    incident_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    active: Mapped[bool] = mapped_column(default=False, nullable=False)


class BrowserSessionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "browser_sessions"
    __table_args__ = (
        Index(
            "ix_browser_sessions_principal_active",
            "principal_id",
            "revoked_at",
            "expires_at",
        ),
    )

    principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))


class ControlPlaneAuditRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "control_plane_audit_log"
    __table_args__ = (
        Index("ix_control_plane_audit_occurred", "occurred_at"),
        Index(
            "ix_control_plane_audit_auth_failures",
            "action",
            "outcome",
            "occurred_at",
        ),
    )

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100))
    trace_id: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str | None] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(100))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))


class AuditArchiveBatchRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_archive_batches"
    __table_args__ = (Index("ix_audit_archive_batches_created", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)


class ResourceRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("environment_id", "name"),
        Index("ix_resources_kind", "kind"),
    )

    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    criticality: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ResourceRelationRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resource_relations"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "relation_type"),)

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)


class PolicyRuleRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "policy_rules"
    __table_args__ = (
        UniqueConstraint("environment_id", "name"),
        CheckConstraint("effect IN ('allow', 'deny')", name="policy_effect"),
        Index("ix_policy_rules_environment_priority", "environment_id", "priority"),
    )

    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    effect: Mapped[PolicyEffect] = mapped_column(
        Enum(
            PolicyEffect,
            name="policy_effect",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    autonomy_levels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    risk_levels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    resource_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    approval_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    maintenance_days: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    maintenance_start_minute: Mapped[int | None] = mapped_column(Integer)
    maintenance_end_minute: Mapped[int | None] = mapped_column(Integer)
    max_executions_per_incident: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class PolicyDecisionRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "policy_decision_snapshots"
    __table_args__ = (
        Index(
            "ix_policy_decisions_incident_rule_allowed",
            "incident_id",
            "matched_rule_id",
            "allowed",
        ),
        Index("ix_policy_decisions_evaluated_at", "evaluated_at"),
    )

    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluated_by: Mapped[str] = mapped_column(String(100), nullable=False)
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(150), nullable=False)
    autonomy_level: Mapped[str] = mapped_column(String(2), nullable=False)
    risk: Mapped[str] = mapped_column(String(20), nullable=False)
    allowed: Mapped[bool] = mapped_column(nullable=False)
    approval_required: Mapped[bool] = mapped_column(nullable=False)
    matched_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_rules.id", ondelete="SET NULL")
    )
    matched_rule_version: Mapped[int | None] = mapped_column(Integer)
    effect: Mapped[str | None] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)


class ApprovalRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("policy_decision_id"),
        Index("ix_approvals_incident_status_created", "incident_id", "status", "created_at"),
        Index("ix_approvals_status_expires", "status", "expires_at"),
    )

    policy_decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_decision_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(
            ApprovalStatus,
            name="approval_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(String(2000))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    editable_parameter_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ActionProposalRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "action_proposals"
    __table_args__ = (
        UniqueConstraint("run_id", "node_execution_id"),
        Index("ix_action_proposals_incident_status", "incident_id", "status"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_execution_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("plan_steps.id", ondelete="SET NULL")
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(150), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    verification_criteria: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    rollback_capability: Mapped[str | None] = mapped_column(String(150))
    risk: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[ActionProposalStatus] = mapped_column(
        Enum(
            ActionProposalStatus,
            name="action_proposal_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    policy_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_decision_snapshots.id", ondelete="RESTRICT")
    )
    approval_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approvals.id", ondelete="RESTRICT")
    )
    action_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("action_requests.id", ondelete="SET NULL")
    )
    decision_reason: Mapped[str | None] = mapped_column(String(2000))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ActionRequestRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "action_requests"
    __table_args__ = (
        UniqueConstraint("environment_id", "idempotency_key"),
        UniqueConstraint(
            "policy_decision_id", name="uq_action_requests_policy_decision_id"
        ),
        UniqueConstraint("approval_id", name="uq_action_requests_approval_id"),
        Index("ix_action_requests_incident_status_created", "incident_id", "status", "created_at"),
    )

    policy_decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_decision_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    approval_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approvals.id", ondelete="RESTRICT")
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[ActionRequestStatus] = mapped_column(
        Enum(
            ActionRequestStatus,
            name="action_request_status",
            native_enum=False,
            length=32,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    verification_criteria: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    rollback_capability: Mapped[str | None] = mapped_column(String(150))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    cancelled_by: Mapped[str | None] = mapped_column(String(100))
    cancellation_reason: Mapped[str | None] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ResourceLockRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resource_locks"
    __table_args__ = (
        UniqueConstraint("resource_id"),
        Index("ix_resource_locks_action_released", "action_request_id", "released_at"),
        Index("ix_resource_locks_expires", "expires_at"),
    )

    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False
    )
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False
    )
    action_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("action_requests.id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[str | None] = mapped_column(String(100))
    reconciliation_required: Mapped[bool] = mapped_column(default=False, nullable=False)


class ActionExecutionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "action_executions"
    __table_args__ = (
        UniqueConstraint("action_request_id"),
        Index("ix_action_executions_runner_status", "runner_id", "status"),
        Index("ix_action_executions_status_lease", "status", "lease_expires_at"),
    )

    action_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("action_requests.id", ondelete="CASCADE"), nullable=False
    )
    runner_id: Mapped[UUID] = mapped_column(
        ForeignKey("runner_instances.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ActionRequestStatus] = mapped_column(
        Enum(
            ActionRequestStatus,
            name="action_execution_status",
            native_enum=False,
            length=32,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    runner_fencing_token: Mapped[int | None] = mapped_column(BigInteger)
    execution_fencing_token: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    resource_fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_completion_id: Mapped[UUID | None] = mapped_column()
    result_summary: Mapped[str | None] = mapped_column(String(2000))
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ActionVerificationRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "action_verifications"
    __table_args__ = (
        UniqueConstraint("action_request_id"),
        Index("ix_action_verifications_status_created", "status", "created_at"),
    )

    action_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("action_requests.id", ondelete="CASCADE"), nullable=False
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ActionVerificationStatus] = mapped_column(
        Enum(
            ActionVerificationStatus,
            name="action_verification_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    criteria_snapshot: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    connector: Mapped[str] = mapped_column(String(50), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_summary: Mapped[str | None] = mapped_column(String(2000))
    error_code: Mapped[str | None] = mapped_column(String(100))
    evidence_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"))
    compensation_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class CompensationRequestRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "compensation_requests"
    __table_args__ = (
        UniqueConstraint("action_request_id"),
        UniqueConstraint("environment_id", "idempotency_key"),
        Index("ix_compensations_incident_status", "incident_id", "status"),
    )

    action_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("action_requests.id", ondelete="CASCADE"), nullable=False
    )
    verification_id: Mapped[UUID] = mapped_column(
        ForeignKey("action_verifications.id", ondelete="RESTRICT"), nullable=False
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(150), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[CompensationStatus] = mapped_column(
        Enum(
            CompensationStatus,
            name="compensation_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decision_comment: Mapped[str | None] = mapped_column(String(2000))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_reason: Mapped[str | None] = mapped_column(String(2000))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class CompensationExecutionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "compensation_executions"
    __table_args__ = (
        UniqueConstraint("compensation_request_id"),
        Index("ix_compensation_executions_runner_status", "runner_id", "status"),
        Index("ix_compensation_executions_status_lease", "status", "lease_expires_at"),
    )

    compensation_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("compensation_requests.id", ondelete="CASCADE"), nullable=False
    )
    runner_id: Mapped[UUID] = mapped_column(
        ForeignKey("runner_instances.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[CompensationStatus] = mapped_column(
        Enum(
            CompensationStatus,
            name="compensation_execution_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    runner_fencing_token: Mapped[int | None] = mapped_column(BigInteger)
    execution_fencing_token: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    resource_fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_completion_id: Mapped[UUID | None] = mapped_column()
    result_summary: Mapped[str | None] = mapped_column(String(2000))
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class IncidentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_status_updated_at", "status", "updated_at"),
        Index("ix_incidents_severity_created_at", "severity", "created_at"),
        Index("ix_incidents_observability_runner", "observability_runner_id", "status"),
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status", native_enum=False),
        default=IncidentStatus.DETECTED,
        nullable=False,
    )
    severity: Mapped[Severity] = mapped_column(
        Enum(
            Severity,
            name="incident_severity",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    owner: Mapped[str | None] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    event_cursor: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        default=0,
        server_default="0",
        nullable=False,
    )
    trace_id: Mapped[UUID] = mapped_column(default=uuid4, unique=True, nullable=False)
    autonomy_level: Mapped[str] = mapped_column(String(2), default="L1", nullable=False)
    replan_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_budget_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_budget_limit: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    observability_runner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("runner_instances.id", ondelete="SET NULL"),
        index=True,
    )
    observability_lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IncidentEventRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_occurred", "incident_id", "occurred_at"),)

    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class EvidenceRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_incident_collected", "incident_id", "collected_at"),
        Index("ix_evidence_resource_collected", "resource_id", "collected_at"),
    )

    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resources.id", ondelete="SET NULL"),
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    redacted: Mapped[bool] = mapped_column(default=False, nullable=False)
    observed_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collection_status: Mapped[str] = mapped_column(
        String(30),
        default="succeeded",
        server_default="succeeded",
        nullable=False,
    )
    time_confidence: Mapped[str] = mapped_column(
        String(30),
        default="runner_reported",
        server_default="runner_reported",
        nullable=False,
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class HypothesisRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "hypotheses"
    __table_args__ = (
        UniqueConstraint("incident_id", "ordinal"),
        Index("ix_hypotheses_incident_status", "incident_id", "status"),
        Index("ix_hypotheses_incident_confidence", "incident_id", "confidence"),
    )

    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[HypothesisStatus] = mapped_column(
        Enum(
            HypothesisStatus,
            name="hypothesis_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        default=HypothesisStatus.PROPOSED,
        nullable=False,
    )
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    contradicting_evidence_ids: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class InvestigationRunRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "investigation_runs"
    __table_args__ = (Index("ix_investigation_runs_incident_status", "incident_id", "status"),)

    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[InvestigationRunStatus] = mapped_column(
        Enum(
            InvestigationRunStatus,
            name="investigation_run_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        default=InvestigationRunStatus.QUEUED,
        nullable=False,
    )
    graph_version: Mapped[str] = mapped_column(String(50), nullable=False)
    current_node: Mapped[str | None] = mapped_column(String(100))
    iteration_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    last_checkpoint_sequence: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    runtime_owner: Mapped[str | None] = mapped_column(String(100), index=True)
    runtime_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    runtime_attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_request_limit: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    model_requests_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_input_tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_output_tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class InvestigationCheckpointRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "investigation_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_investigation_checkpoints_run_sequence",
        ),
        UniqueConstraint(
            "run_id",
            "node_execution_id",
            name="uq_investigation_checkpoints_run_node_execution",
        ),
        Index("ix_investigation_checkpoints_run_sequence", "run_id", "sequence"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    node_execution_id: Mapped[str] = mapped_column(String(128), nullable=False)
    node: Mapped[str] = mapped_column(String(100), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(50), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("plan_steps.id", ondelete="SET NULL"),
        index=True,
    )
    hypothesis_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    completed_node_keys: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    no_progress_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progressed: Mapped[bool] = mapped_column(default=True, nullable=False)
    next_action: Mapped[str | None] = mapped_column(String(50))
    model_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvestigationHITLWaitRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "investigation_hitl_waits"
    __table_args__ = (
        UniqueConstraint("run_id", "subject_type", "subject_id"),
        Index("ix_investigation_hitl_waits_run_status", "run_id", "status"),
        Index("ix_investigation_hitl_waits_subject", "subject_type", "subject_id"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    checkpoint_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigation_checkpoints.id", ondelete="RESTRICT"), nullable=False
    )
    subject_type: Mapped[InvestigationHITLSubjectType] = mapped_column(
        Enum(
            InvestigationHITLSubjectType,
            name="investigation_hitl_subject_type",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    subject_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[InvestigationHITLWaitStatus] = mapped_column(
        Enum(
            InvestigationHITLWaitStatus,
            name="investigation_hitl_wait_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    outcome: Mapped[str | None] = mapped_column(String(50))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class InvestigationObservationWaitRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "investigation_observation_waits"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "node_execution_id",
            name="uq_investigation_observation_waits_run_node_execution",
        ),
        UniqueConstraint(
            "runner_task_id",
            name="uq_investigation_observation_waits_runner_task_id",
        ),
        Index("ix_investigation_observation_waits_run_status", "run_id", "status"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    checkpoint_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigation_checkpoints.id", ondelete="RESTRICT"), nullable=False
    )
    plan_step_id: Mapped[UUID] = mapped_column(
        ForeignKey("plan_steps.id", ondelete="RESTRICT"), nullable=False
    )
    runner_task_id: Mapped[UUID] = mapped_column(
        ForeignKey("runner_tasks.id", ondelete="RESTRICT"), nullable=False
    )
    node_execution_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[InvestigationObservationWaitStatus] = mapped_column(
        Enum(
            InvestigationObservationWaitStatus,
            name="investigation_observation_wait_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    outcome: Mapped[str | None] = mapped_column(String(50))
    evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class PlanRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("incident_id", "version"),
        Index("ix_plans_incident_status", "incident_id", "status"),
    )

    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(
        Enum(
            PlanStatus,
            name="plan_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        default=PlanStatus.ACTIVE,
        nullable=False,
    )
    max_tool_calls: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    replan_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PlanStepRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plan_steps"
    __table_args__ = (
        UniqueConstraint("plan_id", "ordinal"),
        Index("ix_plan_steps_plan_status", "plan_id", "status"),
    )

    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    step_type: Mapped[PlanStepType] = mapped_column(
        Enum(
            PlanStepType,
            name="plan_step_type",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    resource_scope: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_capabilities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    expected_evidence: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    success_criteria: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    risk: Mapped[PlanStepRisk] = mapped_column(
        Enum(
            PlanStepRisk,
            name="plan_step_risk",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    status: Mapped[PlanStepStatus] = mapped_column(
        Enum(
            PlanStepStatus,
            name="plan_step_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        default=PlanStepStatus.PENDING,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class OutboxEventRecord(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_incident_sequence", "incident_id", "sequence"),
        Index("ix_outbox_pending", "published_at", "sequence"),
        Index(
            "ix_outbox_delivery_due",
            "published_at",
            "dead_lettered_at",
            "next_attempt_at",
            "sequence",
        ),
    )

    sequence: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[UUID] = mapped_column(default=uuid4, unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    trace_id: Mapped[UUID] = mapped_column(nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    last_status_code: Mapped[int | None] = mapped_column(Integer)


class AlertRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("source", "dedup_key"),
        Index("ix_alerts_status_last_seen", "status", "last_seen_at"),
        Index("ix_alerts_incident_received", "incident_id", "received_at"),
    )

    source: Mapped[str] = mapped_column(String(50), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[AlertStatus] = mapped_column(
        Enum(
            AlertStatus,
            name="alert_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    severity: Mapped[Severity] = mapped_column(
        Enum(
            Severity,
            name="alert_severity",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    labels: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    annotations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    generator_url: Mapped[str | None] = mapped_column(Text)
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resources.id", ondelete="SET NULL"),
        index=True,
    )
    incident_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"),
    )


class RunnerRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runner_instances"

    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    status: Mapped[RunnerStatus] = mapped_column(
        Enum(
            RunnerStatus,
            name="runner_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        default=RunnerStatus.ONLINE,
        nullable=False,
    )
    software_version: Mapped[str] = mapped_column(String(50), nullable=False)
    environment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL"),
        index=True,
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    labels: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_token_hash: Mapped[str | None] = mapped_column(String(64))
    previous_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_id: Mapped[UUID | None] = mapped_column()
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class RunnerLeaseRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "runner_leases"

    runner_id: Mapped[UUID] = mapped_column(
        ForeignKey("runner_instances.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    fencing_token: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunnerTaskRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runner_tasks"
    __table_args__ = (
        UniqueConstraint(
            "action_verification_id", name="uq_runner_tasks_action_verification_id"
        ),
        Index("ix_runner_tasks_status_created", "status", "created_at"),
        Index("ix_runner_tasks_runner_status", "runner_id", "status"),
    )

    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("plan_steps.id", ondelete="SET NULL"),
        index=True,
    )
    action_verification_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("action_verifications.id", ondelete="CASCADE"),
        index=True,
    )
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    runner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("runner_instances.id", ondelete="SET NULL"),
        index=True,
    )
    connector: Mapped[str] = mapped_column(String(50), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[RunnerTaskStatus] = mapped_column(
        Enum(
            RunnerTaskStatus,
            name="runner_task_status",
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
        ),
        default=RunnerTaskStatus.QUEUED,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_fencing_token: Mapped[int | None] = mapped_column(BigInteger)
    last_completion_id: Mapped[UUID | None] = mapped_column()
    evidence_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"))
    result_summary: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    output_truncated: Mapped[bool] = mapped_column(default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
