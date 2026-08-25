"""Add persistent Agent Action Proposals.

Revision ID: 20260814_0029
Revises: 20260813_0028
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0029"
down_revision: str | Sequence[str] | None = "20260813_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

proposal_status = sa.Enum(
    "proposed",
    "denied",
    "awaiting_approval",
    "action_ready",
    "rejected",
    "cancelled",
    name="action_proposal_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "action_proposals",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_execution_id", sa.String(128), nullable=False),
        sa.Column("plan_step_id", sa.Uuid()),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(150), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("verification_criteria", sa.JSON(), nullable=False),
        sa.Column("rollback_capability", sa.String(150)),
        sa.Column("risk", sa.String(20), nullable=False),
        sa.Column("status", proposal_status, nullable=False),
        sa.Column("policy_decision_id", sa.Uuid()),
        sa.Column("approval_id", sa.Uuid()),
        sa.Column("action_request_id", sa.Uuid()),
        sa.Column("decision_reason", sa.String(2000)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["investigation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_step_id"], ["plan_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["policy_decision_id"], ["policy_decision_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["action_request_id"], ["action_requests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_action_proposals"),
        sa.UniqueConstraint(
            "run_id",
            "node_execution_id",
            name="uq_action_proposals_run_id",
        ),
    )
    op.create_index(
        "ix_action_proposals_incident_status",
        "action_proposals",
        ["incident_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("action_proposals")
