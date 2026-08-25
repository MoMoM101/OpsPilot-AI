"""Expand Action status columns for the complete state machine.

Revision ID: 20260814_0031
Revises: 20260814_0030
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0031"
down_revision: str | Sequence[str] | None = "20260814_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "action_requests",
        "status",
        existing_type=sa.String(length=11),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "action_executions",
        "status",
        existing_type=sa.String(length=11),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "action_executions",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=11),
        existing_nullable=False,
    )
    op.alter_column(
        "action_requests",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=11),
        existing_nullable=False,
    )
