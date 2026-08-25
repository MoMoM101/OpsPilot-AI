"""Add Runner instances and heartbeat leases.

Revision ID: 20260809_0006
Revises: 20260809_0005
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0006"
down_revision: str | Sequence[str] | None = "20260809_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

runner_status = sa.Enum(
    "online",
    "offline",
    "draining",
    "disabled",
    name="runner_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "runner_instances",
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("status", runner_status, nullable=False),
        sa.Column("software_version", sa.String(50), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_runner_instances_environment_id_environments",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_runner_instances"),
        sa.UniqueConstraint("name", name="uq_runner_instances_name"),
    )
    op.create_index(
        "ix_runner_instances_environment_id",
        "runner_instances",
        ["environment_id"],
    )
    op.create_table(
        "runner_leases",
        sa.Column("runner_id", sa.Uuid(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["runner_id"],
            ["runner_instances.id"],
            name="fk_runner_leases_runner_id_runner_instances",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_runner_leases"),
        sa.UniqueConstraint("runner_id", name="uq_runner_leases_runner_id"),
    )


def downgrade() -> None:
    op.drop_table("runner_leases")
    op.drop_table("runner_instances")
