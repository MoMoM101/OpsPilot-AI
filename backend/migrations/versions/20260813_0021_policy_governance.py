"""Add Policy governance and immutable decision snapshots.

Revision ID: 20260813_0021
Revises: 20260812_0020
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0021"
down_revision: str | Sequence[str] | None = "20260812_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("policy_rules") as batch_op:
        batch_op.add_column(
            sa.Column("maintenance_days", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(sa.Column("maintenance_start_minute", sa.Integer()))
        batch_op.add_column(sa.Column("maintenance_end_minute", sa.Integer()))
        batch_op.add_column(sa.Column("max_executions_per_incident", sa.Integer()))
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "policy_decision_snapshots",
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_by", sa.String(100), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(150), nullable=False),
        sa.Column("autonomy_level", sa.String(2), nullable=False),
        sa.Column("risk", sa.String(20), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("matched_rule_id", sa.Uuid()),
        sa.Column("matched_rule_version", sa.Integer()),
        sa.Column("effect", sa.String(10)),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matched_rule_id"], ["policy_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_policy_decision_snapshots"),
    )
    op.create_index(
        "ix_policy_decisions_evaluated_at",
        "policy_decision_snapshots",
        ["evaluated_at"],
    )
    op.create_index(
        "ix_policy_decisions_incident_rule_allowed",
        "policy_decision_snapshots",
        ["incident_id", "matched_rule_id", "allowed"],
    )


def downgrade() -> None:
    op.drop_table("policy_decision_snapshots")
    with op.batch_alter_table("policy_rules") as batch_op:
        batch_op.drop_column("version")
        batch_op.drop_column("max_executions_per_incident")
        batch_op.drop_column("maintenance_end_minute")
        batch_op.drop_column("maintenance_start_minute")
        batch_op.drop_column("maintenance_days")
