"""Add Policy-authorized idempotent Action Requests.

Revision ID: 20260813_0023
Revises: 20260813_0022
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0023"
down_revision: str | Sequence[str] | None = "20260813_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

action_status = sa.Enum(
    "ready",
    "dispatching",
    "running",
    "succeeded",
    "failed",
    "unknown",
    "cancelled",
    name="action_request_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "action_requests",
        sa.Column("policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid()),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(150), nullable=False),
        sa.Column("status", action_status, nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("verification_criteria", sa.JSON(), nullable=False),
        sa.Column("rollback_capability", sa.String(150)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("cancelled_by", sa.String(100)),
        sa.Column("cancellation_reason", sa.String(1000)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["policy_decision_id"],
            ["policy_decision_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_action_requests"),
        sa.UniqueConstraint(
            "environment_id",
            "idempotency_key",
            name="uq_action_requests_environment_id",
        ),
    )
    op.create_index(
        "ix_action_requests_incident_status_created",
        "action_requests",
        ["incident_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("action_requests")
