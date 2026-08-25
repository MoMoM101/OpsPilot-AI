"""Add leased Runner Action Executions and reconciliation holds.

Revision ID: 20260813_0025
Revises: 20260813_0024
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0025"
down_revision: str | Sequence[str] | None = "20260813_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

execution_status = sa.Enum(
    "ready",
    "dispatching",
    "running",
    "succeeded",
    "failed",
    "unknown",
    "cancelled",
    name="action_execution_status",
    native_enum=False,
)


def upgrade() -> None:
    with op.batch_alter_table("resource_locks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "reconciliation_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.create_table(
        "action_executions",
        sa.Column("action_request_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["action_request_id"], ["action_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["runner_id"], ["runner_instances.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_action_executions"),
        sa.UniqueConstraint("action_request_id", name="uq_action_executions_action_request_id"),
    )
    op.create_index(
        "ix_action_executions_runner_status",
        "action_executions",
        ["runner_id", "status"],
    )
    op.create_index(
        "ix_action_executions_status_lease",
        "action_executions",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_table("action_executions")
    with op.batch_alter_table("resource_locks") as batch_op:
        batch_op.drop_column("reconciliation_required")
