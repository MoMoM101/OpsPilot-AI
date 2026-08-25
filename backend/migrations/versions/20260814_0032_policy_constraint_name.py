"""Align the Policy effect constraint with metadata naming conventions.

Revision ID: 20260814_0032
Revises: 20260814_0031
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0032"
down_revision: str | Sequence[str] | None = "20260814_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_CONSTRAINT = "policy_effect"
TARGET_CONSTRAINT = "ck_policy_rules_policy_effect"


def _constraint_names() -> set[str]:
    constraints = sa.inspect(op.get_bind()).get_check_constraints("policy_rules")
    return {
        name
        for constraint in constraints
        if (name := constraint.get("name")) is not None
    }


def upgrade() -> None:
    constraint_names = _constraint_names()
    if TARGET_CONSTRAINT in constraint_names:
        return

    with op.batch_alter_table("policy_rules") as batch_op:
        if LEGACY_CONSTRAINT in constraint_names:
            batch_op.drop_constraint(op.f(LEGACY_CONSTRAINT), type_="check")
        batch_op.create_check_constraint(
            op.f(TARGET_CONSTRAINT),
            "effect IN ('allow', 'deny')",
        )


def downgrade() -> None:
    constraint_names = _constraint_names()
    if TARGET_CONSTRAINT not in constraint_names:
        return

    with op.batch_alter_table("policy_rules") as batch_op:
        batch_op.drop_constraint(op.f(TARGET_CONSTRAINT), type_="check")
        if LEGACY_CONSTRAINT not in constraint_names:
            batch_op.create_check_constraint(
                op.f(LEGACY_CONSTRAINT),
                "effect IN ('allow', 'deny')",
            )
