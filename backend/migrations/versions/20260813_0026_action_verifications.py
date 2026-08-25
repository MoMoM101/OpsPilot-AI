"""Add post-Action verification records and Runner task linkage.

Revision ID: 20260813_0026
Revises: 20260813_0025
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0026"
down_revision: str | Sequence[str] | None = "20260813_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

verification_status = sa.Enum(
    "queued",
    "running",
    "passed",
    "failed",
    "unknown",
    name="action_verification_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "action_verifications",
        sa.Column("action_request_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("status", verification_status, nullable=False),
        sa.Column("criteria_snapshot", sa.JSON(), nullable=False),
        sa.Column("connector", sa.String(50), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.String(2000)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("evidence_id", sa.Uuid()),
        sa.Column(
            "compensation_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["action_request_id"], ["action_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_action_verifications"),
        sa.UniqueConstraint("action_request_id", name="uq_action_verifications_action_request_id"),
    )
    op.create_index(
        "ix_action_verifications_status_created",
        "action_verifications",
        ["status", "created_at"],
    )
    with op.batch_alter_table("runner_tasks") as batch_op:
        batch_op.add_column(sa.Column("action_verification_id", sa.Uuid()))
        batch_op.create_foreign_key(
            "fk_runner_tasks_action_verification_id_action_verifications",
            "action_verifications",
            ["action_verification_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_runner_tasks_action_verification_id", ["action_verification_id"]
        )
        batch_op.create_index("ix_runner_tasks_action_verification_id", ["action_verification_id"])


def downgrade() -> None:
    with op.batch_alter_table("runner_tasks") as batch_op:
        batch_op.drop_index("ix_runner_tasks_action_verification_id")
        batch_op.drop_constraint("uq_runner_tasks_action_verification_id", type_="unique")
        batch_op.drop_constraint(
            "fk_runner_tasks_action_verification_id_action_verifications",
            type_="foreignkey",
        )
        batch_op.drop_column("action_verification_id")
    op.drop_table("action_verifications")
