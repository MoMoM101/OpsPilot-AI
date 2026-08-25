"""Add structured incident hypotheses.

Revision ID: 20260810_0010
Revises: 20260809_0009
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0010"
down_revision: str | Sequence[str] | None = "20260809_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

hypothesis_status = sa.Enum(
    "proposed",
    "supported",
    "weakened",
    "rejected",
    "confirmed",
    name="hypothesis_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "hypotheses",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("status", hypothesis_status, nullable=False),
        sa.Column("supporting_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("contradicting_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_hypotheses_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hypotheses"),
        sa.UniqueConstraint(
            "incident_id",
            "ordinal",
            name="uq_hypotheses_incident_id",
        ),
    )
    op.create_index("ix_hypotheses_incident_id", "hypotheses", ["incident_id"])
    op.create_index(
        "ix_hypotheses_incident_status",
        "hypotheses",
        ["incident_id", "status"],
    )
    op.create_index(
        "ix_hypotheses_incident_confidence",
        "hypotheses",
        ["incident_id", "confidence"],
    )


def downgrade() -> None:
    op.drop_table("hypotheses")
