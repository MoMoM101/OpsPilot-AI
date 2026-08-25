"""Align environment slug index with ORM metadata.

Revision ID: 20260807_0003
Revises: 20260807_0002
Create Date: 2026-08-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260807_0003"
down_revision: str | Sequence[str] | None = "20260807_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("environments") as batch_op:
        batch_op.drop_constraint("uq_environments_slug", type_="unique")
        batch_op.drop_index("ix_environments_slug")
        batch_op.create_index("ix_environments_slug", ["slug"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("environments") as batch_op:
        batch_op.drop_index("ix_environments_slug")
        batch_op.create_index("ix_environments_slug", ["slug"], unique=False)
        batch_op.create_unique_constraint("uq_environments_slug", ["slug"])
