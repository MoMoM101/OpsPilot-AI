"""Add Agent runtime leases and resumable checkpoint routing.

Revision ID: 20260811_0013
Revises: 20260811_0012
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0013"
down_revision: str | Sequence[str] | None = "20260811_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("investigation_runs", sa.Column("runtime_owner", sa.String(100)))
    op.add_column(
        "investigation_runs",
        sa.Column("runtime_lease_expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "investigation_runs",
        sa.Column("runtime_attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_investigation_runs_runtime_owner",
        "investigation_runs",
        ["runtime_owner"],
    )
    op.create_index(
        "ix_investigation_runs_runtime_lease_expires_at",
        "investigation_runs",
        ["runtime_lease_expires_at"],
    )
    op.add_column(
        "investigation_checkpoints",
        sa.Column("progressed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "investigation_checkpoints",
        sa.Column("next_action", sa.String(50)),
    )


def downgrade() -> None:
    op.drop_column("investigation_checkpoints", "next_action")
    op.drop_column("investigation_checkpoints", "progressed")
    op.drop_index(
        "ix_investigation_runs_runtime_lease_expires_at",
        table_name="investigation_runs",
    )
    op.drop_index("ix_investigation_runs_runtime_owner", table_name="investigation_runs")
    op.drop_column("investigation_runs", "runtime_attempt")
    op.drop_column("investigation_runs", "runtime_lease_expires_at")
    op.drop_column("investigation_runs", "runtime_owner")
