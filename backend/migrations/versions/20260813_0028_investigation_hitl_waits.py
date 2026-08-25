"""Add persistent Investigation human-in-the-loop waits.

Revision ID: 20260813_0028
Revises: 20260813_0027
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0028"
down_revision: str | Sequence[str] | None = "20260813_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

subject_type = sa.Enum(
    "approval", "compensation", name="investigation_hitl_subject_type", native_enum=False
)
wait_status = sa.Enum(
    "waiting",
    "resolved",
    "cancelled",
    name="investigation_hitl_wait_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "investigation_hitl_waits",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", subject_type, nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("status", wait_status, nullable=False),
        sa.Column("outcome", sa.String(50)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resumed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["investigation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["checkpoint_id"], ["investigation_checkpoints.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investigation_hitl_waits"),
        sa.UniqueConstraint(
            "run_id",
            "subject_type",
            "subject_id",
            name="uq_investigation_hitl_waits_run_id",
        ),
    )
    op.create_index(
        "ix_investigation_hitl_waits_run_status",
        "investigation_hitl_waits",
        ["run_id", "status"],
    )
    op.create_index(
        "ix_investigation_hitl_waits_subject",
        "investigation_hitl_waits",
        ["subject_type", "subject_id"],
    )


def downgrade() -> None:
    op.drop_table("investigation_hitl_waits")
