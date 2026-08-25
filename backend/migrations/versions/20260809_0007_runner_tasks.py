"""Add read-only Runner task queue.

Revision ID: 20260809_0007
Revises: 20260809_0006
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0007"
down_revision: str | Sequence[str] | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

runner_task_status = sa.Enum(
    "queued",
    "leased",
    "succeeded",
    "failed",
    "cancelled",
    name="runner_task_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "runner_tasks",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("runner_id", sa.Uuid(), nullable=True),
        sa.Column("connector", sa.String(50), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("status", runner_task_status, nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("task_fencing_token", sa.BigInteger(), nullable=True),
        sa.Column("last_completion_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("output_truncated", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name="fk_runner_tasks_evidence_id_evidence",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_runner_tasks_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            name="fk_runner_tasks_resource_id_resources",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["runner_id"],
            ["runner_instances.id"],
            name="fk_runner_tasks_runner_id_runner_instances",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_runner_tasks"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_runner_tasks_idempotency_key",
        ),
    )
    op.create_index("ix_runner_tasks_incident_id", "runner_tasks", ["incident_id"])
    op.create_index("ix_runner_tasks_resource_id", "runner_tasks", ["resource_id"])
    op.create_index("ix_runner_tasks_runner_id", "runner_tasks", ["runner_id"])
    op.create_index(
        "ix_runner_tasks_status_created",
        "runner_tasks",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_runner_tasks_runner_status",
        "runner_tasks",
        ["runner_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("runner_tasks")
