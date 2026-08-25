"""Align the Policy effect constraint with metadata naming conventions.

Revision ID: 20260814_0032
Revises: 20260814_0031
Create Date: 2026-08-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_0032"
down_revision: str | Sequence[str] | None = "20260814_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE policy_rules "
        "RENAME CONSTRAINT policy_effect TO ck_policy_rules_policy_effect"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE policy_rules "
        "RENAME CONSTRAINT ck_policy_rules_policy_effect TO policy_effect"
    )
