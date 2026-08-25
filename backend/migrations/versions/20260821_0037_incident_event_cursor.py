"""Persist the SSE cursor represented by each Incident snapshot.

Revision ID: 20260821_0037
Revises: 20260821_0036
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0037"
down_revision: str | Sequence[str] | None = "20260821_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "event_cursor",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
    op.execute(
        sa.text(
            """
            UPDATE incidents
            SET event_cursor = COALESCE(
                (
                    SELECT MAX(outbox_events.sequence)
                    FROM outbox_events
                    WHERE outbox_events.incident_id = incidents.id
                ),
                0
            )
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.drop_column("event_cursor")
