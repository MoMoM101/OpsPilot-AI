"""Add normalized Evidence metadata.

Revision ID: 20260809_0008
Revises: 20260809_0007
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0008"
down_revision: str | Sequence[str] | None = "20260809_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.add_column(sa.Column("resource_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("observed_from", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("observed_to", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "collection_status",
                sa.String(30),
                nullable=False,
                server_default="succeeded",
            )
        )
        batch_op.add_column(
            sa.Column(
                "time_confidence",
                sa.String(30),
                nullable=False,
                server_default="runner_reported",
            )
        )
        batch_op.create_foreign_key(
            "fk_evidence_resource_id_resources",
            "resources",
            ["resource_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_evidence_resource_id", "evidence", ["resource_id"])
    op.create_index(
        "ix_evidence_incident_collected",
        "evidence",
        ["incident_id", "collected_at"],
    )
    op.create_index(
        "ix_evidence_resource_collected",
        "evidence",
        ["resource_id", "collected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_resource_collected", table_name="evidence")
    op.drop_index("ix_evidence_incident_collected", table_name="evidence")
    op.drop_index("ix_evidence_resource_id", table_name="evidence")
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.drop_constraint(
            "fk_evidence_resource_id_resources",
            type_="foreignkey",
        )
        batch_op.drop_column("time_confidence")
        batch_op.drop_column("collection_status")
        batch_op.drop_column("collected_at")
        batch_op.drop_column("observed_to")
        batch_op.drop_column("observed_from")
        batch_op.drop_column("resource_id")
