"""Add managed Demo installation ownership manifest.

Revision ID: 20260821_0036
Revises: 20260820_0035
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0036"
down_revision: str | Sequence[str] | None = "20260820_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_installations",
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("manifest_version", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("resource_ids", sa.JSON(), nullable=False),
        sa.Column("incident_ids", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_demo_installations_environment_id_environments",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("key", name="pk_demo_installations"),
        sa.UniqueConstraint("environment_id", name="uq_demo_installations_environment_id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO demo_installations
                (key, manifest_version, generation, environment_id, resource_ids,
                 incident_ids, active, created_at, updated_at)
            VALUES
                ('guided_tour', 1, 0, NULL, '[]', '[]', FALSE,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
    )


def downgrade() -> None:
    op.drop_table("demo_installations")
