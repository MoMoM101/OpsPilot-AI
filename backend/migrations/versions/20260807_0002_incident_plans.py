"""Add incident runtime fields and investigation plans.

Revision ID: 20260807_0002
Revises: 20260807_0001
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0002"
down_revision: str | Sequence[str] | None = "20260807_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

plan_status = sa.Enum(
    "draft",
    "active",
    "completed",
    "superseded",
    "failed",
    name="plan_status",
    native_enum=False,
)
plan_step_type = sa.Enum(
    "observe",
    "analyze",
    "experiment",
    "remediate",
    "verify",
    "human",
    name="plan_step_type",
    native_enum=False,
)
plan_step_risk = sa.Enum(
    "read_only",
    "low",
    "medium",
    "high",
    name="plan_step_risk",
    native_enum=False,
)
plan_step_status = sa.Enum(
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    "blocked",
    name="plan_step_status",
    native_enum=False,
)


def upgrade() -> None:
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.add_column(sa.Column("trace_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("autonomy_level", sa.String(2), server_default="L1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("replan_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("tool_budget_used", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("tool_budget_limit", sa.Integer(), server_default="30", nullable=False)
        )
    op.execute("UPDATE incidents SET trace_id = id WHERE trace_id IS NULL")
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.alter_column("trace_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_unique_constraint("uq_incidents_trace_id", ["trace_id"])

    op.create_table(
        "plans",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", plan_status, nullable=False),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("replan_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_plans_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.UniqueConstraint("incident_id", "version", name="uq_plans_incident_id"),
    )
    op.create_index("ix_plans_incident_status", "plans", ["incident_id", "status"])
    op.create_table(
        "plan_steps",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("step_type", plan_step_type, nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("resource_scope", sa.JSON(), nullable=False),
        sa.Column("allowed_capabilities", sa.JSON(), nullable=False),
        sa.Column("expected_evidence", sa.JSON(), nullable=False),
        sa.Column("success_criteria", sa.JSON(), nullable=False),
        sa.Column("risk", plan_step_risk, nullable=False),
        sa.Column("status", plan_step_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["plans.id"],
            name="fk_plan_steps_plan_id_plans",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_steps"),
        sa.UniqueConstraint("plan_id", "ordinal", name="uq_plan_steps_plan_id"),
    )
    op.create_index("ix_plan_steps_plan_status", "plan_steps", ["plan_id", "status"])


def downgrade() -> None:
    op.drop_table("plan_steps")
    op.drop_table("plans")
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.drop_constraint("uq_incidents_trace_id", type_="unique")
        batch_op.drop_column("tool_budget_limit")
        batch_op.drop_column("tool_budget_used")
        batch_op.drop_column("replan_count")
        batch_op.drop_column("autonomy_level")
        batch_op.drop_column("trace_id")
