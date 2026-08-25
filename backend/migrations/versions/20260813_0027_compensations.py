"""Add independently approved Compensation Requests and executions.

Revision ID: 20260813_0027
Revises: 20260813_0026
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0027"
down_revision: str | Sequence[str] | None = "20260813_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

compensation_status = sa.Enum(
    "pending",
    "approved",
    "rejected",
    "dispatching",
    "running",
    "succeeded",
    "failed",
    "unknown",
    "escalated",
    name="compensation_status",
    native_enum=False,
)
execution_status = sa.Enum(
    "pending",
    "approved",
    "rejected",
    "dispatching",
    "running",
    "succeeded",
    "failed",
    "unknown",
    "escalated",
    name="compensation_execution_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "compensation_requests",
        sa.Column("action_request_id", sa.Uuid(), nullable=False),
        sa.Column("verification_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(150), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("status", compensation_status, nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("decided_by", sa.String(100)),
        sa.Column("decision_comment", sa.String(2000)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("escalation_reason", sa.String(2000)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["action_request_id"], ["action_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["verification_id"], ["action_verifications.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_compensation_requests"),
        sa.UniqueConstraint("action_request_id", name="uq_compensation_requests_action_request_id"),
        sa.UniqueConstraint(
            "environment_id",
            "idempotency_key",
            name="uq_compensation_requests_environment_id",
        ),
    )
    op.create_index(
        "ix_compensations_incident_status",
        "compensation_requests",
        ["incident_id", "status"],
    )
    op.create_table(
        "compensation_executions",
        sa.Column("compensation_request_id", sa.Uuid(), nullable=False),
        sa.Column("runner_id", sa.Uuid(), nullable=False),
        sa.Column("status", execution_status, nullable=False),
        sa.Column("runner_fencing_token", sa.BigInteger()),
        sa.Column("execution_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("resource_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_completion_id", sa.Uuid()),
        sa.Column("result_summary", sa.String(2000)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["compensation_request_id"],
            ["compensation_requests.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["runner_id"], ["runner_instances.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_compensation_executions"),
        sa.UniqueConstraint(
            "compensation_request_id",
            name="uq_compensation_executions_compensation_request_id",
        ),
    )
    op.create_index(
        "ix_compensation_executions_runner_status",
        "compensation_executions",
        ["runner_id", "status"],
    )
    op.create_index(
        "ix_compensation_executions_status_lease",
        "compensation_executions",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_table("compensation_executions")
    op.drop_table("compensation_requests")
