"""Add transactional outbox events.

Revision ID: 20260808_0004
Revises: 20260807_0003
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0004"
down_revision: str | Sequence[str] | None = "20260807_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column(
            "sequence",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_outbox_events_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("sequence", name="pk_outbox_events"),
        sa.UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
    )
    op.create_index(
        "ix_outbox_events_aggregate_id",
        "outbox_events",
        ["aggregate_id"],
    )
    op.create_index(
        "ix_outbox_incident_sequence",
        "outbox_events",
        ["incident_id", "sequence"],
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_events",
        ["published_at", "sequence"],
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
