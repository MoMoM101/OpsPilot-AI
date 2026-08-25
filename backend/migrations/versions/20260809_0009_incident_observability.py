"""Track Incident observability ownership.

Revision ID: 20260809_0009
Revises: 20260809_0008
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0009"
down_revision: str | Sequence[str] | None = "20260809_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.add_column(sa.Column("observability_runner_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "observability_lost_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_incidents_observability_runner_id_runner_instances",
            "runner_instances",
            ["observability_runner_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_incidents_observability_runner_id",
        "incidents",
        ["observability_runner_id"],
    )
    op.create_index(
        "ix_incidents_observability_runner",
        "incidents",
        ["observability_runner_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_observability_runner", table_name="incidents")
    op.drop_index("ix_incidents_observability_runner_id", table_name="incidents")
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.drop_constraint(
            "fk_incidents_observability_runner_id_runner_instances",
            type_="foreignkey",
        )
        batch_op.drop_column("observability_lost_at")
        batch_op.drop_column("observability_runner_id")
