"""Add persistent investigation runs and checkpoints.

Revision ID: 20260811_0012
Revises: 20260810_0011
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0012"
down_revision: str | Sequence[str] | None = "20260810_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

investigation_run_status = sa.Enum(
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    name="investigation_run_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "investigation_runs",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", investigation_run_status, nullable=False),
        sa.Column("graph_version", sa.String(50), nullable=False),
        sa.Column("current_node", sa.String(100), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("last_checkpoint_sequence", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_investigation_runs_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investigation_runs"),
        sa.UniqueConstraint("thread_id", name="uq_investigation_runs_thread_id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_investigation_runs_idempotency_key",
        ),
    )
    op.create_index("ix_investigation_runs_incident_id", "investigation_runs", ["incident_id"])
    op.create_index(
        "ix_investigation_runs_incident_status",
        "investigation_runs",
        ["incident_id", "status"],
    )

    op.create_table(
        "investigation_checkpoints",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_execution_id", sa.String(128), nullable=False),
        sa.Column("node", sa.String(100), nullable=False),
        sa.Column("graph_version", sa.String(50), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("plan_step_id", sa.Uuid(), nullable=True),
        sa.Column("hypothesis_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("completed_node_keys", sa.JSON(), nullable=False),
        sa.Column("no_progress_count", sa.Integer(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_step_id"],
            ["plan_steps.id"],
            name="fk_investigation_checkpoints_plan_step_id_plan_steps",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["investigation_runs.id"],
            name="fk_investigation_checkpoints_run_id_investigation_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investigation_checkpoints"),
        sa.UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_investigation_checkpoints_run_sequence",
        ),
        sa.UniqueConstraint(
            "run_id",
            "node_execution_id",
            name="uq_investigation_checkpoints_run_node_execution",
        ),
    )
    op.create_index(
        "ix_investigation_checkpoints_run_id",
        "investigation_checkpoints",
        ["run_id"],
    )
    op.create_index(
        "ix_investigation_checkpoints_plan_step_id",
        "investigation_checkpoints",
        ["plan_step_id"],
    )
    op.create_index(
        "ix_investigation_checkpoints_run_sequence",
        "investigation_checkpoints",
        ["run_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_table("investigation_checkpoints")
    op.drop_table("investigation_runs")
