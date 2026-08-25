"""Add normalized alerts.

Revision ID: 20260809_0005
Revises: 20260808_0004
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0005"
down_revision: str | Sequence[str] | None = "20260808_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

alert_status = sa.Enum(
    "firing",
    "resolved",
    name="alert_status",
    native_enum=False,
)
alert_severity = sa.Enum(
    "critical",
    "high",
    "medium",
    "low",
    name="alert_severity",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("status", alert_status, nullable=False),
        sa.Column("severity", alert_severity, nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("annotations", sa.JSON(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("generator_url", sa.Text(), nullable=True),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_alerts_incident_id_incidents",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            name="fk_alerts_resource_id_resources",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
        sa.UniqueConstraint("source", "dedup_key", name="uq_alerts_source"),
    )
    op.create_index("ix_alerts_resource_id", "alerts", ["resource_id"])
    op.create_index(
        "ix_alerts_incident_received",
        "alerts",
        ["incident_id", "received_at"],
    )
    op.create_index(
        "ix_alerts_status_last_seen",
        "alerts",
        ["status", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_table("alerts")
