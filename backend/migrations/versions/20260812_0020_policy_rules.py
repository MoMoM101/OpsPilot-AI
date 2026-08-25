"""Add environment-scoped Policy rules.

Revision ID: 20260812_0020
Revises: 20260812_0019
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0020"
down_revision: str | Sequence[str] | None = "20260812_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

policy_effect = sa.Enum("allow", "deny", name="policy_effect", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "policy_rules",
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("effect", policy_effect, nullable=False),
        sa.Column("autonomy_levels", sa.JSON(), nullable=False),
        sa.Column("risk_levels", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("resource_ids", sa.JSON(), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_policy_rules_environment_id_environments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_policy_rules"),
        sa.UniqueConstraint("environment_id", "name", name="uq_policy_rules_environment_id"),
    )
    op.create_index("ix_policy_rules_environment_id", "policy_rules", ["environment_id"])
    op.create_index(
        "ix_policy_rules_environment_priority",
        "policy_rules",
        ["environment_id", "priority"],
    )


def downgrade() -> None:
    op.drop_table("policy_rules")
