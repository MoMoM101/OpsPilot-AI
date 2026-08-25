"""Add control-plane authentication principals.

Revision ID: 20260811_0015
Revises: 20260811_0014
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0015"
down_revision: str | Sequence[str] | None = "20260811_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

principal_kind = sa.Enum("user", "service", name="principal_kind", native_enum=False)
principal_role = sa.Enum(
    "admin", "operator", "viewer", "runtime", name="principal_role", native_enum=False
)


def upgrade() -> None:
    op.create_table(
        "api_principals",
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", principal_kind, nullable=False),
        sa.Column("role", principal_role, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("environment_ids", sa.JSON(), nullable=False),
        sa.Column("unrestricted_environments", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_api_principals"),
        sa.UniqueConstraint("name", name="uq_api_principals_name"),
        sa.UniqueConstraint("token_hash", name="uq_api_principals_token_hash"),
    )
    op.create_index("ix_api_principals_active", "api_principals", ["active"])
    op.create_table(
        "control_plane_audit_log",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(100), nullable=False),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("actor_role", sa.String(30), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(100)),
        sa.Column("trace_id", sa.String(100)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_control_plane_audit_log"),
    )
    op.create_index(
        "ix_control_plane_audit_log_actor_id",
        "control_plane_audit_log",
        ["actor_id"],
    )
    op.create_index(
        "ix_control_plane_audit_occurred",
        "control_plane_audit_log",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("control_plane_audit_log")
    op.drop_table("api_principals")
