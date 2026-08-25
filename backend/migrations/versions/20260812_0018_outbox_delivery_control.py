"""Add Outbox retry scheduling and Dead Letter fields.

Revision ID: 20260812_0018
Revises: 20260812_0017
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0018"
down_revision: str | Sequence[str] | None = "20260812_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("outbox_events") as batch_op:
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("dead_lettered_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("last_error", sa.String(1000)))
        batch_op.add_column(sa.Column("last_status_code", sa.Integer()))
        batch_op.create_index(
            "ix_outbox_delivery_due",
            ["published_at", "dead_lettered_at", "next_attempt_at", "sequence"],
        )


def downgrade() -> None:
    with op.batch_alter_table("outbox_events") as batch_op:
        batch_op.drop_index("ix_outbox_delivery_due")
        batch_op.drop_column("last_status_code")
        batch_op.drop_column("last_error")
        batch_op.drop_column("dead_lettered_at")
        batch_op.drop_column("next_attempt_at")
