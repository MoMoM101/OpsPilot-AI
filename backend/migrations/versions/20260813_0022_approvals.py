"""Add Policy-bound human approvals.

Revision ID: 20260813_0022
Revises: 20260813_0021
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0022"
down_revision: str | Sequence[str] | None = "20260813_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

approval_status = sa.Enum(
    "pending",
    "approved",
    "rejected",
    "expired",
    name="approval_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(150), nullable=False),
        sa.Column("status", approval_status, nullable=False),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("decided_by", sa.String(100)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_comment", sa.String(2000)),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("editable_parameter_keys", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["policy_decision_id"],
            ["policy_decision_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
        sa.UniqueConstraint("policy_decision_id", name="uq_approvals_policy_decision_id"),
    )
    op.create_index(
        "ix_approvals_incident_status_created",
        "approvals",
        ["incident_id", "status", "created_at"],
    )
    op.create_index("ix_approvals_status_expires", "approvals", ["status", "expires_at"])


def downgrade() -> None:
    op.drop_table("approvals")
