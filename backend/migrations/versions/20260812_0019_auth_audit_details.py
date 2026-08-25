"""Add authentication audit result and source fields.

Revision ID: 20260812_0019
Revises: 20260812_0018
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0019"
down_revision: str | Sequence[str] | None = "20260812_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("control_plane_audit_log") as batch_op:
        batch_op.add_column(sa.Column("action", sa.String(100)))
        batch_op.add_column(sa.Column("outcome", sa.String(30)))
        batch_op.add_column(sa.Column("error_code", sa.String(100)))
        batch_op.add_column(sa.Column("source_ip", sa.String(64)))
        batch_op.add_column(sa.Column("user_agent_hash", sa.String(64)))
        batch_op.create_index(
            "ix_control_plane_audit_auth_failures",
            ["action", "outcome", "occurred_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("control_plane_audit_log") as batch_op:
        batch_op.drop_index("ix_control_plane_audit_auth_failures")
        batch_op.drop_column("user_agent_hash")
        batch_op.drop_column("source_ip")
        batch_op.drop_column("error_code")
        batch_op.drop_column("outcome")
        batch_op.drop_column("action")
