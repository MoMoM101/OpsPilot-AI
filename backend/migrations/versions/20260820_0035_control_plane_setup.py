"""Add one-time Control Plane setup state.

Revision ID: 20260820_0035
Revises: 20260820_0034
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0035"
down_revision: str | Sequence[str] | None = "20260820_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "control_plane_setup",
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_principal_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["completed_by_principal_id"],
            ["api_principals.id"],
            name="fk_control_plane_setup_completed_by_principal_id_api_principals",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name="pk_control_plane_setup"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO control_plane_setup
                (key, completed_at, completed_by_principal_id)
            SELECT
                'initial_admin',
                CASE WHEN EXISTS (
                    SELECT 1 FROM api_principals
                    WHERE active IS TRUE AND kind = 'user' AND role = 'admin'
                ) THEN CURRENT_TIMESTAMP ELSE NULL END,
                (
                    SELECT id FROM api_principals
                    WHERE active IS TRUE AND kind = 'user' AND role = 'admin'
                    ORDER BY created_at, id
                    LIMIT 1
                )
            """
        )
    )


def downgrade() -> None:
    op.drop_table("control_plane_setup")
