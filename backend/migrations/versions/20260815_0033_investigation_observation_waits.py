"""Add persistent waits for Agent observations.

Revision ID: 20260815_0033
Revises: 20260814_0032
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0033"
down_revision: str | Sequence[str] | None = "20260814_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

wait_status = sa.Enum(
    "waiting",
    "resolved",
    "cancelled",
    name="investigation_observation_wait_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "investigation_observation_waits",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("plan_step_id", sa.Uuid(), nullable=False),
        sa.Column("runner_task_id", sa.Uuid(), nullable=False),
        sa.Column("node_execution_id", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(1000), nullable=False),
        sa.Column("status", wait_status, nullable=False),
        sa.Column("outcome", sa.String(50)),
        sa.Column("evidence_id", sa.Uuid()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resumed_at", sa.DateTime(timezone=True)),
        sa.Column("model_requests", sa.Integer(), nullable=False),
        sa.Column("model_input_tokens", sa.Integer(), nullable=False),
        sa.Column("model_output_tokens", sa.Integer(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["investigation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["checkpoint_id"], ["investigation_checkpoints.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["plan_step_id"], ["plan_steps.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["runner_task_id"], ["runner_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_investigation_observation_waits"),
        sa.UniqueConstraint(
            "run_id",
            "node_execution_id",
            name="uq_investigation_observation_waits_run_node_execution",
        ),
        sa.UniqueConstraint(
            "runner_task_id",
            name="uq_investigation_observation_waits_runner_task_id",
        ),
    )
    op.create_index(
        "ix_investigation_observation_waits_run_status",
        "investigation_observation_waits",
        ["run_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("investigation_observation_waits")
