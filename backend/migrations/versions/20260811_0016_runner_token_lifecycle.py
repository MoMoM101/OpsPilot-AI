"""Add Runner token rotation and expiry metadata.

Revision ID: 20260811_0016
Revises: 20260811_0015
Create Date: 2026-08-11
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0016"
down_revision: str | Sequence[str] | None = "20260811_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runner_instances") as batch_op:
        batch_op.add_column(sa.Column("token_issued_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("token_expires_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("previous_token_hash", sa.String(64)))
        batch_op.add_column(sa.Column("previous_token_expires_at", sa.DateTime(timezone=True)))

    now = datetime.now(UTC)
    runner_instances = sa.table(
        "runner_instances",
        sa.column("token_issued_at"),
        sa.column("token_expires_at"),
    )
    op.execute(
        sa.update(runner_instances).values(
            token_issued_at=now,
            token_expires_at=now + timedelta(days=7),
        )
    )
    with op.batch_alter_table("runner_instances") as batch_op:
        batch_op.alter_column(
            "token_issued_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch_op.alter_column(
            "token_expires_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("runner_instances") as batch_op:
        batch_op.drop_column("previous_token_expires_at")
        batch_op.drop_column("previous_token_hash")
        batch_op.drop_column("token_expires_at")
        batch_op.drop_column("token_issued_at")
