"""Add Principal token lifecycle and browser sessions.

Revision ID: 20260812_0017
Revises: 20260811_0016
Create Date: 2026-08-12
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0017"
down_revision: str | Sequence[str] | None = "20260811_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_principals") as batch_op:
        batch_op.add_column(sa.Column("token_issued_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("token_expires_at", sa.DateTime(timezone=True)))

    now = datetime.now(UTC)
    principals = sa.table(
        "api_principals",
        sa.column("token_issued_at"),
        sa.column("token_expires_at"),
    )
    op.execute(
        sa.update(principals).values(
            token_issued_at=now,
            token_expires_at=now + timedelta(days=30),
        )
    )
    with op.batch_alter_table("api_principals") as batch_op:
        batch_op.alter_column("token_issued_at", nullable=False)
        batch_op.alter_column("token_expires_at", nullable=False)

    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent_hash", sa.String(64)),
        sa.ForeignKeyConstraint(["principal_id"], ["api_principals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_browser_sessions_principal_active",
        "browser_sessions",
        ["principal_id", "revoked_at", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_browser_sessions_principal_active", table_name="browser_sessions")
    op.drop_table("browser_sessions")
    with op.batch_alter_table("api_principals") as batch_op:
        batch_op.drop_column("token_expires_at")
        batch_op.drop_column("token_issued_at")
